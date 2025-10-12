from fastapi import HTTPException, Header
from openai import OpenAI
import logging
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
import os
from pinecone import PodSpec, Pinecone
from langchain_pinecone import Pinecone as l_Pinecone
import random
import string
from datetime import datetime
import tiktoken
from typing import List

TEXT_EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-3.5-turbo"
CHUNK_SIZE, CHUNK_OVERLAP = 100, 20
RANDOM_STR_LEN = 10

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def auth_user(auth: str = Header()):
    #    print("Authorization: ", auth)
    if auth == "validated_user":
        return True
    else:
        raise HTTPException(401, {"message": "unauthorised"})


embed = OpenAIEmbeddings(
    model=TEXT_EMBEDDING_MODEL,
    openai_api_key=os.environ["OPENAI_API_KEY"],
)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Defines the cloud and region where the index should be deployed
# Read more about it here - https://docs.pinecone.io/docs/create-an-index
spec = PodSpec(environment="gcp-starter")
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("canopy--serverless-index-1")
text_field = "text"  # the metadata field that contains our text
vectorstore = l_Pinecone(index, embed.embed_query, text_field)


def get_embedding(text: str, model: str = TEXT_EMBEDDING_MODEL) -> List[float]:
    # todo: add a text sanity check -- text should be long enough to make sense -- initially can't be empty.
    text = text.replace("\n", " ")
    result = embed.embed_documents([text])
    #    logger.warning(f"returning embedding for text: {result}")
    return result[0]


def get_chunks(text):
    """
    # LLaMA-2 LLM Context is 4096 tokens so split document into chunks
    # Chunks are 1000 tokens with 200 token overlap
    # Should get 4439 chunks if all goes well
    # LLM Token Chunksize varies based on Context Window. LLaMA2 Context Window is 4096 tokens.
    # For QA want to pick larger chunk size with some overlap to get context.
    """

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=tiktoken_len,
        is_separator_regex=False,
    )
    texts = text_splitter.split_text(text)
    logger.warning(f"got the following count of chunks: {len(texts)}")
    return texts


tokenizer = tiktoken.get_encoding("cl100k_base")


# create the length function
def tiktoken_len(text):
    tokens = tokenizer.encode(text, disallowed_special=())
    return len(tokens)


def insert_db(text, embedding):
    id = "".join(random.choices(string.ascii_uppercase, k=RANDOM_STR_LEN))
    logger.warning(f"inside insert_db with id {id}")

    index.upsert(
        vectors=[
            {
                "id": id,
                "values": embedding,
                "metadata": dict(
                    created_at=datetime.now().isoformat(),
                    title="aiy",
                    text=text,
                ),
            }
        ],
        namespace="aiy",
    )


def get_similar_texts(query):
    query = query or "the glass is half full"
    embedding = get_embedding(query)
    records = index.query(
        vector=embedding,
        top_k=100,
        include_values=False,
        include_metadata=True,
        namespace="aiy",
    )
    documents = [record.metadata["text"] for record in records.matches]
    return documents


def get_llm_response(query):
    messages = build_query_prompt(query)
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=2048,
            frequency_penalty=0.0,
        )
        summary = response.choices[0].message.content
        return summary
    except Exception as e:
        print("Failed to make a completion request:", e)
        return None


def build_query_prompt(input_texts):
    input_text = "\n".join(input_texts)
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant: Summirizerthat analyzes the given context from a set of documents. Then, you create a summary of all the information provided. Please keep your summary under 200 words",
        },
        {
            "role": "user",
            "content": f"Here is a list of all the things that we have conversed about: {input_text}",
        },
        {
            "role": "assistant",
            "content": "Great! I've processed all the provided information. What answers do you want",
        },
        {"role": "user", "content": "Please summarize in a structured manner."},
    ]
    return messages
