def build_prompt(tokenizer, prompt_text: str, question_text: str) -> str:
    """Construye el prompt siempre como mensaje de usuario."""
    messages = [
        {"role": "user", "content": f"{prompt_text}\n\n{question_text}"},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )


def print_progress(idx: int, total: int, text: str):
    """Imprime progreso segun reglas: primeros 10, cada 50 hasta 200, cada 100 despues."""
    if idx <= 10 or (idx <= 200 and idx % 50 == 0) or (idx > 200 and idx % 100 == 0):
        print(f"  [{idx:03d}/{total}] {text[:80]}")
