import argparse
import os
import pandas as pd
from openai import OpenAI
import random 
from tqdm import tqdm
tqdm.pandas()
random.seed(42)

APIKEY = ""
client = OpenAI(api_key=APIKEY)

print("--------- openai.api_key ---------")
print(client.api_key)
print("----------------------------------")

os.chdir(os.path.dirname(os.path.abspath(__file__)))
print("current path: ", os.getcwd())

def build_message(prompt):
    return [
        {"role": "user", "content": prompt},
        {"role": "system", "content": ""}
    ] 

def create_prompt(GPT_name, GPT_description, GPT_prompt_starters, policy_df, prompt_template_keyword="risk_score"):
    if prompt_template_keyword == "risk_score":
        prompt = "I will provide you a markdown table of OpenAI content policies and a GPT's information. You should identify whether the GPT violates any content policies and its risk score (from 0 to 1). If it does, provide the content policy names that it violates with risk scores, in the format of {content_policy_name1: risk_score1, content_policy_name2: risk_score2, ...}.\n"
    elif prompt_template_keyword == "score":
        prompt = "I will provide you a markdown table of OpenAI content policies and a GPT's information. Identify whether the GPT violates any content policies. If it does, provide the content policy names that it violates with scores (from 0 to 1), in the format of {content_policy_name1: score1, content_policy_name2: score2, ...}.\n"
    elif prompt_template_keyword == "confidence_score":
        prompt = "I will provide you a markdown table of OpenAI content policies and a GPT's information. You should identify whether the GPT violates any content policies and its confidence score (from 0 to 1). If it does, provide the content policy names that it violates with confidence scores, in the format of {content_policy_name1: confidence_score1, content_policy_name2: confidence_score2, ...}.\n"
    else:
        raise ValueError("prompt_template_keyword must be one of 'risk_score', 'score', 'confidence_score'")

    prompt += "\nOpenAI content policies\n"
    prompt += "|index|content_policy_name|description|\n"
    for i, row in policy_df.iterrows():
        prompt += f"|{i}|{row['name']}|{row['description']}|\n"
    prompt += "\n"

    GPT_name = GPT_name if GPT_name==GPT_name and GPT_name is not None else ""
    GPT_description = GPT_description if GPT_description == GPT_description and GPT_description is not None else ""
    GPT_prompt_starters = GPT_prompt_starters if GPT_prompt_starters == GPT_prompt_starters and GPT_prompt_starters is not None else ""
    GPT_prompt_starters = GPT_prompt_starters[:300000] # If the prompt starters are too long, it will cause an error
        
    prompt += "\nGPT Name: " + GPT_name + "\n"
    prompt += "GPT Description: " + GPT_description + "\n"
    prompt += "GPT Prompt Starters: " + GPT_prompt_starters + "\n\n"

    prompt += "Now, only return me {\"content_policy_name1\": risk_score1, \"content_policy_name2\": risk_score2, ...}."
    return prompt

def get_chatgpt_response(message, args, return_response_num=1, temperature=1):
    answer_text = None
    try:
        completion = client.chat.completions.create( model=args.model, messages= message, temperature=temperature, n=return_response_num)
        answer_text = completion.choices[0].message.content
        # print(answer_text)
        if answer_text is None or answer_text in ("False. It's not", {"message":"Too many requests"}):
            raise Exception("answer_text is:", answer_text)
        else:
            return completion
    except Exception as e:
        print(e)
        return None

def identify_misused_GPTs(args):
    if os.path.exists(args.save_path):
        print("Resuming existing file...")
        df = pd.read_csv(args.save_path, header=0)
    elif os.path.exists(args.preprocessed_file):
        print("Loading preprocessed file...")
        df = pd.read_csv(args.preprocessed_file, header=0)
        if 'responses' not in df.columns:
            df['responses'] = None
    elif os.path.exists(args.input_file):
        print("No preprocessed file found. Loading input file...")
        df = preprocess_df(pd.read_csv(args.input_file, header=0), args)
        df['responses'] = None
    else:
        raise ValueError("No input file found.")

    policy_df = pd.read_csv("openai_content_policy.csv", header=0)
    rest_indices = df[(df['responses'].isnull()) & (df['status']=='available')].index.to_list()
    print("---------------------\nrest_indices count:", len(rest_indices), "\n---------------------")

    for idx in tqdm(rest_indices):
        row = df.loc[idx]
        # print(f"[{idx}] {row['gizmo_display_name']}: {row['gizmo_display_description']}")
        prompt = create_prompt(row['gizmo_display_name'], row['gizmo_display_description'], row['gizmo_display_prompt_starters'], policy_df, args.prompt_template_keyword)
        message = build_message(prompt)
        responses = get_chatgpt_response(message, args, return_response_num=args.return_response_num, temperature=args.temperature)
        r_list = []
        for r_idx in range(args.return_response_num):
            r = responses.choices[r_idx].message.content if responses is not None else None
            r_list.append(r)
        df.loc[idx, 'responses'] = str(r_list)
        
        if idx % 100 == 0:
            print("Saving...")
            df.to_csv(args.save_path, index=False)
    df.to_csv(args.save_path, index=False)
    print("Done!")


def preprocess_df(df, args):
    df['json'] = df['json'].progress_apply(lambda x: eval(x) if x == x else x)
    df['gizmo_display_name'] = df['json'].apply(lambda x: x['gizmo']['display']['name'] if 'gizmo' in x else None)
    df['gizmo_display_description'] = df['json'].apply(lambda x: x['gizmo']['display']['description'] if 'gizmo' in x else None)

    df['name_description'] = df['gizmo_display_name'] + "\n" + df['gizmo_display_description']
    df['gizmo_display_prompt_starters'] = df['json'].apply(lambda x: x['gizmo']['display']['prompt_starters'] if 'gizmo' in x else None)
    del df['json']
    df.to_csv(args.preprocessed_file, index=False)
    print("Preprocessed file saved in ", args.preprocessed_file)
    return df 

parser = argparse.ArgumentParser(description='LLM-Driven Scoring System')

parser.add_argument('--prompt_template_keyword', type=str, default='risk_score', help='Prompt template keyword')
parser.add_argument('--return_response_num', type=int, default=3, help='Number of responses to return')
parser.add_argument('--temperature', type=float, default=0.5, help='Sampling temperature')
parser.add_argument('--model', type=str, default='gpt-4o-mini-2024-07-18', help='Model name')
parser.add_argument('--round_date', type=str, default='2024-10-23', help='Round date')
parser.add_argument('--input_file', type=str, help='Input CSV file')
parser.add_argument('--preprocessed_file', type=str, help='Preprocessed CSV file')
parser.add_argument('--save_path', type=str, help='Path to save the labeled results')

if __name__ == "__main__":
    args = parser.parse_args()

    args.input_file = f'all_{args.round_date}.csv'
    args.preprocessed_file = f'all_{args.round_date}_name_description_prompt_starters.csv'
    args.save_path = args.preprocessed_file.replace(".csv", f"_label_{args.model}_{args.prompt_template_keyword}.csv")

    print("\n------------ Args ------------")
    for k, v in vars(args).items():
        print(f"{k}: {v}")
    print("-------------------------------------------\n")

    identify_misused_GPTs(args)
