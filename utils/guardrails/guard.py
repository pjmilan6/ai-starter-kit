import argparse
import os
from typing import Any, Dict, List, Optional, Union

import yaml
from dotenv import load_dotenv
from langchain_core.prompts import load_prompt

guardrails_dir = os.path.dirname(os.path.abspath(__file__))
utils_dir = os.path.abspath(os.path.join(guardrails_dir, '..'))
repo_dir = os.path.abspath(os.path.join(utils_dir, '..'))

load_dotenv(os.path.join(repo_dir, '.env'))

from utils.model_wrappers.api_gateway import APIGateway


class Guard:
    """
    Guard class for running guardrails check with Sambanova's models.
    """

    def __init__(
        self,
        api: str = 'sncloud',
        prompt_path: Optional[str] = None,
        guardrails_path: Optional[str] = None,
        model: Optional[str] = 'Meta-Llama-Guard-3-8B',
        sambastudio_url: Optional[str] = None,
        sambastudio_api_key: Optional[str] = None,
        sambanova_url: Optional[str] = None,
        sambanova_api_key: Optional[str] = None,
    ) -> None:
        """
        Initialize Guard class with specified LLM and guardrails.

        Parameters:
        - api (str): The LLM API to use, default is 'sambastudio'.
        - prompt_path (str, optional): Path to the prompt YAML file. Default is 'utils/guardrails/prompt.yaml'.
        - guardrails_path (str, optional): Path to the guardrails YAML file. Default is
         'utils/guardrails/guardrails.yaml'.
        - model (str, optional): guard model to use set if using bundle models or sncloud as api
            default is: Meta-Llama-Guard-3-8B
        - sambastudio_base_url (str, optional): URL for SambaStudio API.
        - sambastudio_api_key (str, optional): API key for SambaStudio API.
        - sambanova_url (str, optional): SambaNova Cloud URL.
        - sambanova_api_key (str, optional): SambaNova Cloud API key.

        """
        if prompt_path is None:
            prompt_path = os.path.join(guardrails_dir, 'prompt.yaml')
        self.prompt = load_prompt(prompt_path)
        if guardrails_path is None:
            guardrails_path = os.path.join(guardrails_dir, 'guardrails.yaml')
        self.guardrails, self.parsed_guardrails = self.load_guardrails(guardrails_path)

        # pass the parameters from Guard to the model gateway to instance de guardrails models
        self.llm = APIGateway.load_chat(
            type=api,
            streaming=False,
            do_sample=False,
            max_tokens=1024,
            temperature=0.1,
            model=model,
            process_prompt=False,
            sambastudio_url=sambastudio_url,
            sambastudio_api_key=sambastudio_api_key,
            sambanova_url=sambanova_url,
            sambanova_api_key=sambanova_api_key,
        )

    def load_guardrails(self, path: str) -> tuple[dict, str]:
        """
        Load enabled guardrails from a YAML file and return them as a dictionary and a formatted string.

        Parameters:
        - path (str): The path to the YAML file containing the guardrails.

        Returns:
        - guardrails (dict): A dictionary of guardrails, where the keys are the guardrail IDs and the values are
         dictionaries containing the guardrail name and details.
        - guardrails_str (str): A formatted string containing the names and descriptions of the enabled guardrails.
        """
        with open(path, 'r') as yaml_file:
            guardrails = yaml.safe_load(yaml_file)

        # filter out disabled guardrails
        enabled_guardrails = {k: v for k, v in guardrails.items() if v.get('enabled')}
        guardrails_list = [f"{k}: {v.get('name')}\n{v.get('description')}" for k, v in enabled_guardrails.items()]
        guardrails_str = '\n'.join(guardrails_list)
        return guardrails, guardrails_str

    def evaluate(
        self,
        input_query: Union[List[Dict], str],
        role: str,
        error_message: Optional[str] = None,
        return_guardrail_type: bool = True,
        raise_exception: bool = False,
    ) -> Union[str, List[str], List[Dict[Any, Any]]]:
        """
        Evaluate a message or a conversation against the guardrails.

        Parameters:
        - input_query (Union[List[Dict], str]): The message or conversation to evaluate. It can be a string with the
         message or a list of dictionaries representing a conversation.
            Example conversation input
            [
             {"role":"user", "content":"this is an user message"},
             {"role":"assistant","content":"this is an assistant response"},
            ]
        - role (str): The role of the message to analyse. It can be either 'user' or 'assistant'.
        - error_message (str, optional): The error message to be displayed when the message violates the guardrails.
         If not provided, a default message "The message violate guardrails" will be used.
        - return_guardrail_type (bool, optional): If True, the function will return the violated guardrail types.
         If False, it will only return the error message. Default is True.
        - raise_exception (bool, optional): If True, the function will raise a ValueError with the error message when
         the message violates the guardrails. If False, it will return the error message without raising the exception.
         Default is False.

        Returns:
        - Union[str, List[str]]: The result of the evaluation. If the message violates the guardrails, it will return
         the error message with the violated guardrail types based on the return_guardrail_type parameter.
        If the message passes the guardrails, it will return the input message or conversation.

        Raises:
        - ValueError: If the role is not 'user' or 'assistant'.
        - ValueError: If the message violates the guardrails when raises_exception is True.
        """

        # parse single query to a conversation structure
        if isinstance(input_query, str):
            if role.lower() == 'user':
                conversation = f'User: {input_query}'
            elif role.lower() == 'assistant':
                conversation = f'Assistant: {input_query}'
            else:
                raise ValueError(f'Invalid role: {role}, only User and Assistant')

        # parse list of messages to a conversation structure
        elif isinstance(input_query, List):
            conversation = ''
            for message in input_query:
                if message['role'].lower() == 'user':
                    conversation += f"User: {message['content']}\n"
                elif message['role'].lower() == 'assistant':
                    conversation += f"Assistant: {message['content']}\n"

        # format prompt
        values = {
            'conversation': input_query,
            'guardrails': self.parsed_guardrails,
            'role': conversation,
        }
        formatted_input = self.prompt.format(**values)

        # guardrail model call
        result = self.llm.invoke(formatted_input)

        # check if the message violates the guardrails
        if 'unsafe' in result.content:
            violated_categories = result.content.split('\n')[-1].split(',')
            violated_categories = [
                f'{k}: {v.get("name")}' for k, v in self.guardrails.items() if k in violated_categories
            ]
            if error_message is None:
                error_message = f'The message violate guardrails'
            response_msg = f'{error_message}\nViolated categories: {", ".join(violated_categories)}'
            if raise_exception:
                raise ValueError(response_msg)
            else:
                if return_guardrail_type:
                    return response_msg
                else:
                    return error_message
        else:
            return input_query


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--message', type=str, help='message to check')
    parser.add_argument('--role', type=str, help='role of the message')
    parser.add_argument('--api', default='sambastudio', type=str, help='api to use')
    args = parser.parse_args()
    guardrails = Guard(api=args.api)
    print(guardrails.evaluate(args.message, args.role))
