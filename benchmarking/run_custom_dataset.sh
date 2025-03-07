#!/bin/bash
# run_custom_dataset.sh

ulimit -n 4096
python src/evaluator.py \
--mode custom \
--model-name "Meta-Llama-3.3-70B-Instruct" \
--results-dir "./data/results/llmperf" \
--num-concurrent-requests 1 \
--timeout 600 \
--input-file-path "<CUSTOM DATASET PATH HERE>" \
--save-llm-responses False \
--sampling-params '{"max_tokens_to_generate": 256}' \
--llm-api sncloud

# Notes:
# 1. Replace <CUSTOM DATASET PATH HERE> with the path to your custom dataset.
#
# 2. For Bundle Models, make sure to include the prefix "Bundle/" before the expert name.
#   For example:
#      --model-name "Bundle/llama-2-7b-chat-hf"
#          OR
#      --model-name "Bundle/llama-2-13b-chat-hf"
#          OR
#      --model-name "Bundle/Mistral-7B-Instruct-v0.2"
#          OR
#      --model-name "Bundle/Meta-Llama-3-8B-Instruct"
#
# 3. For Non-Bundle models, use the model name directly and remember to update and source the `.env` file for a new endpoint.
#   For example:
#      --model-name "llama-2-7b-chat-hf"
#          OR
#      --model-name "llama-2-13b-chat-hf"
#          OR
#      --model-name "Mistral-7B-Instruct-v0.2"
#          OR
#      --model-name "Meta-Llama-3-8B-Instruct"
#
# 4. For SambaNovaCloud endpoints, change the llm-api parameter to "snloud" and use the model name directly.
#   For example:
#      --model-names "Meta-Llama-3.1-8B-Instruct"
#
