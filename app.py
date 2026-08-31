# app.py
import gradio as gr
from new_backend import graph
import uuid

def extract_text(value):
    """Extrae texto limpio si el valor es un objeto mensaje, lista de bloques o dict."""
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, list):
        # Si Gemini devuelve bloques estructurados [{'type': 'text', 'text': '...'}]
        parts = []
        for item in value:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif hasattr(item, "content"):
                parts.append(str(item.content))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(value, dict) and "text" in value:
        return value["text"]
    return str(value)

# --- Función que será llamada por Gradio para ejecutar el agente ---
def generate_essay(topic: str, max_revisions: int):
    thread_id = str(uuid.uuid4())
    thread_config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "task": topic,
        "max_revisions": max_revisions,
        "revision_number": 0,
        "plan": "",
        "draft": "",
        "critique": "",
        "content": []
    }

    full_output = ""
    for s in graph.stream(initial_state, thread_config):
        step_output = list(s.values())[0]

        if "plan" in step_output:
            plan_text = extract_text(step_output['plan'])
            full_output += f"### 📋 Plan Generado:\n{plan_text}\n\n"

        elif "content" in step_output:
            content_list = step_output['content']
            if isinstance(content_list, list):
                search_content = "\n".join(extract_text(c) for c in content_list)
            else:
                search_content = extract_text(content_list)
            full_output += f"### 🔍 Contenido de Investigación:\n{search_content}\n\n"

        elif "draft" in step_output:
            draft_text = extract_text(step_output['draft'])
            full_output += f"### ✍️ Borrador Generado:\n{draft_text}\n\n"

        elif "critique" in step_output:
            critique_text = extract_text(step_output['critique'])
            full_output += f"### 🧐 Critica y Revisión:\n{critique_text}\n\n"

        # Línea separadora limpia
        full_output += f"{'-' * 60}\n\n"
        
        yield full_output

# -- Creación de la Interfaz Gradio --
with gr.Blocks(theme=gr.themes.Default(spacing_size="sm", text_size="sm")) as demo:
    gr.Markdown("# 🤖 Generador de Redacciones con Gemini y LangGraph")
    gr.Markdown(
        """
        Escribe el tema de tu redacción y el número de revisiones.
        El agente planificará, investigará, redactará y revisará el texto.
        """
    )
    with gr.Row():
        essay_topic = gr.Textbox(label="Tema de la Redacción", placeholder="Ej: La importancia de la inteligencia artificial en la educación")
        max_revisions_slider = gr.Slider(minimum=0, maximum=5, step=1, value=1, label="Número Máximo de Revisiones")
        generate_button = gr.Button("Generar Redacción", variant="primary")
        
    output_textbox = gr.Textbox(label="Proceso y Redacción Final", lines=20, max_lines=40)

    generate_button.click(
        fn=generate_essay,
        inputs=[essay_topic, max_revisions_slider],
        outputs=output_textbox
    )

if __name__ == "__main__":
    demo.launch(share=False)