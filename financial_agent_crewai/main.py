"""
Main module for the Finanicial Flow.

This module implements a workflow for generating financial content using multiple specialized AI crews.
It handles the coordination between research and content creation phases.
"""

import json
import logging
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

# Must precede any llm module imports
# from langtrace_python_sdk import langtrace
from crewai import LLM
from crewai.flow.flow import Flow, and_, listen, start
from dotenv import load_dotenv
from langchain_sambanova import ChatSambaNovaCloud

from financial_agent_crewai.src.financial_agent_crewai.config import *
from financial_agent_crewai.src.financial_agent_crewai.crews.context_analysis_crew.context_analysis_crew import (
    ContextAnalysisCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.decomposition_crew.decomposition_crew import (
    DecompositionCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.generic_research_crew.generic_research_crew import (
    GenericResearchCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.rag_crew.rag_crew import RAGCrew
from financial_agent_crewai.src.financial_agent_crewai.crews.report_crew.report_crew import ReportCrew
from financial_agent_crewai.src.financial_agent_crewai.crews.sec_edgar_crew.sec_edgar_crew import SECEdgarCrew
from financial_agent_crewai.src.financial_agent_crewai.crews.sorting_hat_crew.sorting_hat_crew import (
    SortingHatCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.summarization_crew.summarization_crew import (
    SummarizationCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.yfinance_news_crew.yfinance_news_crew import (
    YFinanceNewsCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.crews.yfinance_stocks_crew.yfinance_stocks_crew import (
    YFinanceStocksCrew,
)
from financial_agent_crewai.src.financial_agent_crewai.tools.general_tools import (
    SubQueriesList,
    convert_csv_source_to_txt_report_filename,
)
from financial_agent_crewai.src.financial_agent_crewai.tools.report_tools import ReportSummary
from financial_agent_crewai.src.financial_agent_crewai.tools.sorting_hat_tools import FilingsInputsList
from financial_agent_crewai.utils.utilities import *

warnings.filterwarnings('ignore', category=SyntaxWarning, module='pysbd')
load_dotenv()

# langtrace.init(api_key=os.getenv('LANGTRACE_API_KEY'))

logger = logging.getLogger(__name__)


class FinancialFlow(Flow):  # type: ignore
    """
    Financial content generation workflow manager.

    This class orchestrates the process of researching financial topics
    and generating financial content through multiple specialized crews.

    Args:
        query: The user query.
        source_generic_search: Whether to use generic search.
        source_sec_filings: Whether to use SEC filings.
        source_yfinance_news: Whether to use YFinance news.
        source_yfinance_stocks: Whether to use YFinance stocks.
        cache_path: The cache path.
        verbose: The level of verbosity.
    """

    def __init__(
        self,
        query: str,
        source_generic_search: Optional[bool] = None,
        source_sec_filings: Optional[bool] = None,
        source_yfinance_news: Optional[bool] = None,
        source_yfinance_stocks: Optional[bool] = None,
        cache_path: Optional[str | Path] = None,
        verbose: bool = True,
    ) -> None:
        """Initialize the Finance Flow."""
        super().__init__()

        # User query
        self.query = query

        # Data sources
        self.source_generic_search = source_generic_search
        self.source_sec_filings = source_sec_filings
        self.source_yfinance_news = source_yfinance_news
        self.source_yfinance_stocks = source_yfinance_stocks

        # Report paths
        self.final_report_path = str(CACHE_DIR / 'report.md')
        self.report_list: List[str] = list()
        self.generic_report_name = str(CACHE_DIR / 'report_generic_search.txt')

        # General LLM
        self.llm = LLM(model=GENERAL_MODEL, temperature=TEMPERATURE)

        # Create cache path
        if cache_path is not None:
            if isinstance(cache_path, Path):
                self.cache_path = cache_path
            elif isinstance(cache_path, str):
                self.cache_path = Path(cache_path)
            else:
                raise TypeError(f'`cache_path` must be a Path or str. Got {type(cache_path)}')
        else:
            self.cache_path = CACHE_DIR if isinstance(CACHE_DIR, Path) else Path(CACHE_DIR)

        # Create the cache directory if it does not exist
        os.makedirs(self.cache_path, exist_ok=True)

        # Empty cache directory
        clear_directory(self.cache_path)

        # Set the level of verbosity
        self.verbose = verbose

    @start()  # type: ignore
    def generic_research(self) -> Optional[str]:
        """Perform a generic research on the user query."""

        if self.source_generic_search:
            # Call the Generic Research Crew
            GenericResearchCrew(
                llm=LLM(model=GENERIC_RESEARCH_MODEL, temperature=TEMPERATURE),
                filename=self.generic_report_name,
            ).crew().kickoff(inputs={'query': self.query})

            # Add the generic report to the report list
            self.report_list.append(self.generic_report_name)

            # Return the generic report name
            return self.generic_report_name
        else:
            return None

    @start()  # type: ignore
    def query_decomposition(self) -> Any:
        """Decompose the user query into a list of sub-queries."""

        if self.source_sec_filings or self.source_yfinance_news or self.source_yfinance_stocks:
            # Call the Decomposition Crew
            query_list = (
                DecompositionCrew(llm=LLM(model=DECOMPOSITION_MODEL, temperature=TEMPERATURE))
                .crew()
                .kickoff(inputs={'query': self.query})
                .pydantic
            )

            # Whether the original query entails a comparison
            self.is_comparison = query_list.is_comparison

            # Return the list of queries
            return query_list.queries_list
        else:
            return SubQueriesList(queries_list=[self.query], is_comparison=False)

    @listen(query_decomposition)  # type: ignore
    def information_extraction(self, query_list: List[str]) -> Optional[Any]:
        """Extract the relevant information from the user query."""

        if self.source_sec_filings or self.source_yfinance_news or self.source_yfinance_stocks:
            # Concatenate the sub-queries into a long query
            decomposed_query = '.'.join(query_list)

            # Lickoff the Sorting Hat Crew
            company_input_list = (
                SortingHatCrew(llm=LLM(model=INFORMATION_EXTRACTION_MODEL, temperature=TEMPERATURE))
                .crew()
                .kickoff(inputs={'query': decomposed_query})
                .pydantic.inputs_list
            )

            # Return a list of query metadata by company and by time period
            return company_input_list
        else:
            return None

    @listen(information_extraction)  # type: ignore
    def sec_edgar(self, metadata_inputs_list: FilingsInputsList) -> Optional[List[str]]:
        """Retrieve the relevant SEC Edgar filings and perform RAG on the user query."""

        if self.source_sec_filings:
            global_sec_filename = str(self.cache_path / 'comparison_sec_filings.txt')

            sec_reports_list = list()
            for filing_metadata in metadata_inputs_list:
                # Call the SEC EDGAR Crew
                filename = (
                    SECEdgarCrew(
                        llm=LLM(model=SEC_EDGAR_MODEL, temperature=TEMPERATURE),
                        input_variables=filing_metadata,  # type: ignore
                    )
                    .crew()
                    .kickoff()
                    .pydantic.filename
                )

                # Append the filename to the list of SEC reports
                sec_reports_list.append(convert_csv_source_to_txt_report_filename(filename))

                # Call the RAG Crew
                RAGCrew(
                    filename=filename,
                    llm=LLM(model=RAG_MODEL, temperature=TEMPERATURE),
                ).crew().kickoff(
                    {'query': filing_metadata.query},  # type: ignore
                )

                try:
                    # Open the source file in read mode and target file in append mode
                    with open(convert_csv_source_to_txt_report_filename(filename), 'r') as source:
                        content = source.read()

                    # Concatenate the text from the SEC reports
                    with open(global_sec_filename, 'a') as target:
                        # Add delimiter
                        target.write('<start>---\n')
                        target.write(
                            f'Context for the company {filing_metadata.company} and year {filing_metadata.year}.\n'  # type: ignore
                        )
                        # Add the content of the SEC
                        target.write(content)
                        # Add delimiter
                        target.write('\n<end>---\n\n')

                except FileNotFoundError:
                    logger.warning('One of the files was not found. Please check the file paths.')
                except Exception as e:
                    logger.warning(f'An error occurred: {e}')

            # Document comparison
            if len(sec_reports_list) > 1 and self.is_comparison:
                # Extract the text from the global text file
                with open(global_sec_filename, 'r') as source:
                    context = source.read()

                # Call the Context Analysis Crew
                ContextAnalysisCrew(
                    llm=LLM(model=CONTEXT_ANALYSIS_MODEL, temperature=TEMPERATURE),
                    output_file=convert_csv_source_to_txt_report_filename(global_sec_filename),
                ).crew().kickoff(
                    {
                        'context': context,
                        'query': COMPARISON_QUERY,
                    },
                )
                # Append the report to the list of SEC reports
                sec_reports_list.append(convert_csv_source_to_txt_report_filename(global_sec_filename))

            # Append the list of SEC EDGAR reports
            self.report_list.extend(sec_reports_list)

            return sec_reports_list
        else:
            return None

    @listen(information_extraction)  # type: ignore
    def yfinance_news(self, metadata_inputs_list: FilingsInputsList) -> List[str]:
        """Retrieve relevant news articles from Yahoo Finance News for a particular company."""

        if self.source_yfinance_news:
            yfinace_news_reports_list: List[str] = list()
            global_yfinance_news_filename = str(self.cache_path / 'comparison_yfinance_news.txt')

            for filing_metadata in metadata_inputs_list:
                # Call the Yahoo Finance News Crew
                filename = (
                    YFinanceNewsCrew(llm=LLM(model=YFINANCE_NEWS_MODEL, temperature=TEMPERATURE))
                    .crew()
                    .kickoff(
                        {'ticker_symbol': filing_metadata.ticker_symbol},  # type: ignore
                    )
                    .pydantic.filename
                )

                # Call the RAG Crew
                RAGCrew(
                    filename=filename,
                    llm=LLM(model=RAG_MODEL, temperature=TEMPERATURE),
                ).crew().kickoff(
                    {'query': filing_metadata.query},  # type: ignore
                )

                # Append the list of Yahoo Finance News reports
                yfinace_news_reports_list.append(convert_csv_source_to_txt_report_filename(filename))

                try:
                    # Open the source file in read mode and target file in append mode
                    with open(convert_csv_source_to_txt_report_filename(filename), 'r') as source:
                        content = source.read()

                    # Concatenate the text from the SEC reports
                    with open(global_yfinance_news_filename, 'a') as target:
                        # Add delimiter
                        target.write('<start>---\n')
                        # Add title
                        target.write(filing_metadata.company + '\n')  # type: ignore
                        # Add the content of the SEC
                        target.write(content)
                        # Add delimiter
                        target.write('\n<end>---\n')

                except FileNotFoundError:
                    logger.warning('One of the files was not found. Please check the file paths.')
                except Exception as e:
                    logger.warning(f'An error occurred: {e}')

            # Document comparison
            if len(yfinace_news_reports_list) > 1 and self.is_comparison:
                # Extract the text from the global text file
                with open(global_yfinance_news_filename, 'r') as source:
                    context = source.read()
                # Call the Context Analysis Crew
                ContextAnalysisCrew(
                    llm=LLM(model=CONTEXT_ANALYSIS_MODEL, temperature=TEMPERATURE),
                    output_file=convert_csv_source_to_txt_report_filename(global_yfinance_news_filename),
                ).crew().kickoff(
                    {
                        'context': context,
                        'query': COMPARISON_QUERY,
                    },
                )
                # Append the global text file to the list of Yahoo Finance News reports
                yfinace_news_reports_list.append(
                    convert_csv_source_to_txt_report_filename(global_yfinance_news_filename)
                )

            # Append the list of Yahoo Finance News reports
            self.report_list.extend(yfinace_news_reports_list)

            return yfinace_news_reports_list
        else:
            return list()

    @listen(information_extraction)  # type: ignore
    def yfinance_stocks(self, metadata_inputs_list: FilingsInputsList) -> List[str]:
        """Analyse the yfinance stock information for a list of companies."""

        if self.source_yfinance_stocks:
            yfinace_stocks_reports_list: List[str] = list()
            yfinance_stocks_json_list: List[str] = list()
            global_yfinance_stocks_filename = str(self.cache_path / 'comparison_yfinance_stocks.txt')
            for filing_metadata in metadata_inputs_list:
                # Call the YFinance Stocks Crew
                filenames_list = (
                    YFinanceStocksCrew(
                        query=filing_metadata.query,  # type: ignore
                        ticker_symbol=filing_metadata.ticker_symbol,  # type: ignore
                        llm=LLM(model=YFINANCE_STOCKS_MODEL, temperature=TEMPERATURE),
                        pandasai_llm=ChatSambaNovaCloud(model=PANDASAI_MODEL, temperature=TEMPERATURE),
                        start_date=filing_metadata.start_date,  # type: ignore
                        end_date=filing_metadata.end_date,  # type: ignore
                    )
                    .crew()
                    .kickoff()
                ).pydantic.file_output_list

                # Extract the filenames
                filename_txt = filenames_list[0].filename
                filename_json = filenames_list[1].filename
                yfinace_stocks_reports_list.append(filename_txt)
                yfinance_stocks_json_list.append(filename_json)

                # Open the JSON file of tables
                with open(filename_json, 'r', encoding='utf-8') as file:
                    data = json.load(file)

                # Append tables to the text files
                table_dict = dict()
                table_markdown_dict = dict()
                with open(filename_txt, 'a', encoding='utf-8') as target:
                    target.write('\n\n')
                    target.write('<begin data tables>')
                    target.write('\n\n')
                for table_name in data:
                    # Extract the nested JSON strings and parse them
                    table_dict[table_name] = parse_table_str(data[table_name])
                    # Convert parsed data to Markdown tables
                    table_markdown_dict[table_name] = dict_to_markdown_table(table_dict[table_name], table_name)
                    # Write the tables into a single text file
                    with open(filename_txt, 'a', encoding='utf-8') as target:
                        target.write(table_markdown_dict[table_name])
                        target.write('\n\n')
                with open(filename_txt, 'a', encoding='utf-8') as target:
                    target.write('<end data tables>')

                try:
                    # Open the source file in read mode and target file in append mode
                    with open(filename_txt, 'r') as source:
                        content = source.read()

                    # Concatenate the text from the answers
                    with open(global_yfinance_stocks_filename, 'a') as target:
                        # Add delimiter
                        target.write('<start>---\n')
                        # Add title
                        target.write(filing_metadata.company + '\n')  # type: ignore
                        # Add the content
                        target.write(content)
                        # Add delimiter
                        target.write('\n<end>---\n')

                except FileNotFoundError:
                    logger.warning('One of the files was not found. Please check the file paths.')
                except Exception as e:
                    logger.warning(f'An error occurred: {e}')

            # Document comparison
            if len(yfinace_stocks_reports_list) > 1 and self.is_comparison:
                # Extract the text from the global text file
                with open(global_yfinance_stocks_filename, 'r') as source:
                    context = source.read()
                # Call the Context Analysis Crew
                ContextAnalysisCrew(
                    llm=LLM(model=CONTEXT_ANALYSIS_MODEL, temperature=TEMPERATURE),
                    output_file=global_yfinance_stocks_filename,
                ).crew().kickoff(
                    {
                        'context': context,
                        'query': COMPARISON_QUERY,
                    },
                )
                yfinace_stocks_reports_list.append(global_yfinance_stocks_filename)

            # Append the list of Yahoo Finance News reports
            self.report_list.extend(yfinace_stocks_reports_list)

            return yfinace_stocks_reports_list
        else:
            return list()

    @listen(and_(generic_research, sec_edgar, yfinance_news, yfinance_stocks))  # type: ignore
    def report_writing(
        self,
    ) -> Any:
        """Write the final financial report."""

        summary_dict: Dict[str, ReportSummary] = dict()
        appendix_images_dict: Dict[str, List[str]] = dict()
        for report in self.report_list:
            # Load the text file
            with open(report, 'r') as f:
                report_txt = f.read()

            # Create the section filename
            section_filename = str(CACHE_DIR / ('section_' + str(Path(report).name)))

            # Call the Report Crew
            ReportCrew(
                llm=LLM(model=REPORT_MODEL, temperature=TEMPERATURE),
                filename=section_filename,
            ).crew().kickoff(
                {
                    'section': report_txt,
                },
            )

            # Call the Summarization Crew
            summary_dict[report] = (
                SummarizationCrew(
                    llm=LLM(model=REPORT_MODEL, temperature=TEMPERATURE),
                )
                .crew()
                .kickoff(
                    {
                        'section': report_txt,
                    },
                )
                .pydantic
            )

        # Generate the final Markdown report
        generate_final_report(
            final_report_path=self.final_report_path,
            query=self.query,
            summary_dict=summary_dict,
            cache_dir=CACHE_DIR,
            yfinance_stocks_dir=YFINANCE_STOCKS_DIR,
        )

        # Read the Markdown file and convert it to HTML
        with open(self.final_report_path, 'r') as md_file:
            md_content = md_file.read()
        # Clean the Markdown (base64 images, table classes) -> HTML
        cleaned_html = clean_markdown_content(md_content)

        # Convert the cleaned HTML to a PDF
        pdf_data = convert_html_to_pdf(cleaned_html, output_file=self.final_report_path.replace('md', 'pdf'))


def kickoff() -> None:
    """Initialize and start the financial content generation process."""

    finance_flow = FinancialFlow(
        query=USER_QUERY,
        source_generic_search=SOURCE_GENERIC_SEARCH,
        source_sec_filings=SOURCE_SEC_FILINGS,
        source_yfinance_news=SOURCE_YFINANCE_NEWS,
        source_yfinance_stocks=SOURCE_YFINANCE_STOCK,
        verbose=VERBOSE,
    )
    finance_flow.kickoff()


def plot() -> None:
    """Generate and display a visualization of the flow structure."""

    finance_flow = FinancialFlow(query=USER_QUERY)
    plot_filename = str(Path('financial_agent_crewai') / 'flow')
    finance_flow.plot(filename=plot_filename)


if __name__ == '__main__':
    plot()
    kickoff()
