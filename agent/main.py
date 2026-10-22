# main.py · OWNER: Carlos · based on the platform-generated template (agent "Lleva")
from langchain.agents import create_agent
from studio import tool
from simulator import request

from tools import COMMON_TOOLS, NEGO_TOOLS, PLAN_TOOLS

AGENT_NAME = 'Lleva'
STUDIO_MEMORY_ENABLED = True
STUDIO_INTERNET_ENABLED = False

INSTRUCCIONES = """{{SYSTEM_PROMPT}}"""


def build_agent(model):
    return create_agent(model=model,
                        tools=[*COMMON_TOOLS, *NEGO_TOOLS, *PLAN_TOOLS],
                        system_prompt=INSTRUCCIONES)
