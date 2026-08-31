# new_backend.py
import os
from dotenv import load_dotenv
from typing import TypedDict, Annotated, List
import operator
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from tavily import TavilyClient
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import warnings
warnings.filterwarnings("ignore", message=".*TqdmWarning.*")

# Carga las variables de entorno desde el archivo .env
load_dotenv()

# Define las variables de entorno
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Define el estado del agente (AgentState)
class AgentState(TypedDict):
    task: str
    plan: str
    draft: str
    critique: str
    content: List[str]
    revision_number: int
    max_revisions: int

# Define el modelo Pydantic para la salida estructurada
class Queries(BaseModel):
    queries: List[str]

# Inicializa la base de datos para los checkpoints
conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
memory = SqliteSaver(conn)

# Inicializa el modelo de lenguaje
model = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0, GOOGLE_API_KEY=GEMINI_API_KEY)

# Crea un Runnable para la salida estructurada (forma correcta para Gemini)
structured_model = model.with_structured_output(Queries)

# Prompts
PLAN_PROMPT = """Eres un escritor especialista con la tarea de crear un esquema de alto nivel para una redacción. \
Escribe este esquema para el tema proporcionado por el usuario. Presenta un plan de la redacción junto con una lista de consultas de búsqueda \
o instrucción relevante para las secciones."""

WRITER_PROMPT = """Eres un asistente de redacción con la tarea de escribir excelentes redacciones de 5 párrafos. \
Genera la mejor redacción posible para la solicitud del usuario y el esquema inicial. \
Si el usuario proporciona críticas, responde con una versión revisada de tus intentos anteriores. \
Utiliza toda la información a continuación según sea necesario: 

{content}"""

REFLECTION_PROMPT = """Eres un profesor encargado de evaluar un ensayo presentado. \
Genera una crítica detallada y recomendaciones para la entrega del usuario. \
Proporciona observaciones específicas, incluyendo sugerencias sobre extensión, profundidad, estilo, claridad y estructura."""

RESEARCH_PLAN_PROMPT = """Eres un investigador encargado de proporcionar información que pueda ser utilizada \
para redactar el siguiente ensayo. Genera una lista de consultas de búsqueda que permitan recopilar \
toda la información relevante. Genera como máximo 3 consultas."""

RESEARCH_CRITIQUE_PROMPT = """Eres un investigador encargado de proporcionar información que pueda ser utilizada \
para realizar las revisiones solicitadas (según se describe a continuación). \
Genera una lista de consultas de búsqueda que permitan recopilar \
toda la información relevante. Genera como máximo 3 consultas."""

# Inicializa el cliente Tavily
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# Definición de los nodos del LangGraph
def plan_node(state: AgentState):
    messages = [
        SystemMessage(content=PLAN_PROMPT), 
        HumanMessage(content=state['task'])
    ]
    response = model.invoke(messages)
    return {"plan": response.content}

def research_plan_node(state: AgentState):
    queries = structured_model.invoke([
        SystemMessage(content=RESEARCH_PLAN_PROMPT),
        HumanMessage(content=state['task'])
    ])
    content = state['content'] or []
    for q in queries.queries:
        response = tavily.search(query=q, max_results=2)
        for r in response['results']:
            content.append(r['content'])
    return {"content": content}

def generation_node(state: AgentState):
    content = "\n\n".join(state['content'] or [])
    user_message = HumanMessage(
        content=f"{state['task']}\n\nHere is my plan:\n\n{state['plan']}")
    messages = [
        SystemMessage(
            content=WRITER_PROMPT.format(content=content)
        ),
        user_message
        ]
    response = model.invoke(messages)
    return {
        "draft": response.content, 
        "revision_number": state.get("revision_number", 0) + 1
    }

def reflection_node(state: AgentState):
    messages = [
        SystemMessage(content=REFLECTION_PROMPT), 
        HumanMessage(content=state['draft'])
    ]
    response = model.invoke(messages)
    return {"critique": response.content}

def research_critique_node(state: AgentState):
    queries = structured_model.invoke([
        SystemMessage(content=RESEARCH_CRITIQUE_PROMPT),
        HumanMessage(content=state['critique'])
    ])
    content = state['content'] or []
    for q in queries.queries:
        response = tavily.search(query=q, max_results=2)
        for r in response['results']:
            content.append(r['content'])
    return {"content": content}

def should_continue(state):
    if state["revision_number"] > state["max_revisions"]:
        return END
    return "reflect"

# Construcción del Grafo
builder = StateGraph(AgentState)

builder.add_node("planner", plan_node)
builder.add_node("research_plan", research_plan_node)
builder.add_node("generate", generation_node)
builder.add_node("reflect", reflection_node)
builder.add_node("research_critique", research_critique_node)

builder.set_entry_point("planner")

builder.add_conditional_edges(
    "generate", 
    should_continue, 
    {END: END, "reflect": "reflect"}
)

builder.add_edge("planner", "research_plan")
builder.add_edge("research_plan", "generate")
builder.add_edge("reflect", "research_critique")
builder.add_edge("research_critique", "generate")

graph = builder.compile(checkpointer=memory)