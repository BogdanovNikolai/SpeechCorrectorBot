import os
import re
import time
import logging
from typing import List, Tuple
from dotenv import load_dotenv
import requests

# === Настройки проекта ===
load_dotenv()
logger = logging.getLogger(__name__)

# === Utility to load dictionary terms ===
def load_dictionary_terms(path='словарь.txt') -> List[str]:
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
        # Split by comma, handle quoted phrases, strip whitespace
        terms = [w.strip(' "\'') for w in re.split(r',\s*', content)]
        # Remove empty strings
        return [t for t in terms if t]
    except Exception as e:
        logging.error(f"[AI] Ошибка при загрузке словаря: {e}")
        return []


class AIGrammarChecker:
    """
    Класс для проверки грамматики, орфографии и пунктуации с помощью DeepSeek API.
    
    Methods:
        check_text_with_explanations: возвращает список ошибок с объяснением и исправлением
    """

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    MODEL_NAME = "deepseek-chat"
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self):
        if not self.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY не найден в переменных окружения")

    def split_into_sentences(self, text: str) -> List[str]:
        """Разделяет текст на предложения по . ? !"""
        parts = re.split(r'(?<=[.?!])\s*', text)
        return [p.strip() for p in parts if p.strip()]

    def analyze_and_correct(self, sentence: str) -> Tuple[str, str]:
        """Анализирует предложение и возвращает объяснение + исправленный вариант"""
        prompt = f"""
Проанализируй это предложение на наличие грамматических, орфографических и пунктуационных ошибок.

ВАЖНО: Не изменяй слова и фразы, обрамлённые в {{{{ ... }}}}.

Если есть ошибки:
1. Кратко объясни, что было неправильно
2. Предложи исправленный вариант

Если ошибок нет — напиши "Ошибок нет" и оставь предложение без изменений.

Формат ответа:
Объяснение: ...
Исправленное предложение: ...

ПРЕДЛОЖЕНИЕ:
{sentence}
"""

        payload = {
            "model": self.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": 200
        }

        headers = {
            "Authorization": f"Bearer {self.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(self.API_URL, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content'].strip()

            # Парсим ответ
            explanation_part = re.search(r"Объяснение:\s*(.*?)(?=\nИсправленное|$)", content, re.DOTALL)
            corrected_part = re.search(r"Исправленное предложение:\s*(.*)", content)

            explanation = (explanation_part.group(1).strip() if explanation_part else "").strip()
            corrected = corrected_part.group(1).strip() if corrected_part else sentence.strip()
            corrected = corrected.strip("*")

            return explanation, corrected

        except Exception as e:
            logger.error(f"[AI] Ошибка при обращении к DeepSeek: {e}", exc_info=True)
            return "Ошибка при анализе", sentence

    def check_text_with_explanations(self, text: str) -> List[Tuple[str, str, str]]:
        """Проверяет весь текст и возвращает список: (оригинал, исправленный, объяснение)"""
        if not text or not isinstance(text, str):
            logger.warning("[AI] Недостаточно данных для анализа")
            return []

        sentences = self.split_into_sentences(text)
        results = []

        for i, sentence in enumerate(sentences):
            logger.info(f"[AI] Проверяем предложение #{i + 1}: '{sentence}'")

            # Получаем анализ и исправление
            explanation, corrected = self.analyze_and_correct(sentence)

            if corrected != sentence:
                results.append((sentence, corrected, explanation))
            else:
                results.append((sentence, corrected, "Ошибок не найдено"))

        return results