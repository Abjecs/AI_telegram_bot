import logging
from gigachat import GigaChat
import os

GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")

async def ask_gigachat(system_prompt: str, user_text: str) -> str | None:
    """Единый хелпер для запросов к GigaChat. Уменьшает дублирование кода."""
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
            response = await giga.achat({"messages": messages})
            return response.choices[0].message.content
    except Exception as e:
        logging.error(f"GigaChat error: {e}")
        return None
