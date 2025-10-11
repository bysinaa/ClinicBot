from typing import Optional
from src.config import settings

async def consult_medical(question: str) -> str:
    """
    Placeholder for AI medical consultation.
    If OPENAI_API_KEY is provided, you can integrate OpenAI's SDK here.
    """
    if not settings.openai_api_key:
        return "ویژگی مشاوره هوشمند فعال نیست. لطفاً کلید OPENAI_API_KEY را در .env تنظیم کنید."
    try:
        # Lazy import to keep optional
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":"You are a medical assistant. Provide careful, conservative, general information. Do not diagnose."},
                {"role":"user","content":question},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or "پاسخی دریافت نشد."
    except Exception as e:
        return f"خطا در ارتباط با سرویس مشاوره: {e}"
