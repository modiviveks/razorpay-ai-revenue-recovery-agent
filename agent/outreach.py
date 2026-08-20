"""Outreach Generator: Generates customer-centric recovery messages in Hinglish/English."""

from openai import OpenAI
from config import settings
from models import FailureClass

# Standard templates fallback
OUTREACH_TEMPLATES = {
    FailureClass.UPI_TIMEOUT: (
        "Hi {name}, lagta hai aapka ₹{amount:.2f} ka UPI payment time out ho gaya. "
        "Don't worry, aap is link par click karke payment directly and safely retry kar sakte hain: {link}"
    ),
    FailureClass.AUTHENTICATION_FAILED: (
        "Hi {name}, payment ke dauran entered OTP/authentication verify nahi ho paya. "
        "Ek baar details check karke, aap is link se payment retry kar sakte hain: {link}"
    ),
    FailureClass.PAYMENT_CANCELLED: (
        "Hi {name}, aapka secure payment process cancel ho gaya tha. "
        "Agar aap checkout complete karna chahte hain, toh is secure payment link par click karein: {link}"
    ),
    FailureClass.INSUFFICIENT_FUNDS: (
        "Hi {name}, lagta hai aapke account mein balance kam tha, jisse transaction fail ho gaya. "
        "Aap niche diye gaye link par click karke dusra payment method (Card/Netbanking) select kar sakte hain: {link}"
    ),
    FailureClass.CARD_EXPIRED: (
        "Hi {name}, transaction ke liye jo card use kiya gaya tha, wo expired ya invalid hai. "
        "Please alternate payment method ya new card use karne ke liye is link par click karein: {link}"
    ),
    FailureClass.BANK_DECLINE: (
        "Hi {name}, aapke bank ne transaction decline kar diya hai. "
        "App secure alternate methods se checkout complete karne ke liye is link par click kar sakte hain: {link}"
    ),
    FailureClass.GATEWAY_ERROR: (
        "Hi {name}, server/gateway issue ki wajah se payment cancel ho gayi thi. "
        "Ab system stable hai. Aap is link se payment retry karein: {link}"
    ),
    FailureClass.SUBSCRIPTION_FAILED: (
        "Hi {name}, aapka subscription charge verify nahi ho paya. "
        "Apna payment mandate check karne ya update karne ke liye is link par click karein: {link}"
    ),
    FailureClass.UNKNOWN: (
        "Hi {name}, payment decline ho gaya tha. "
        "Please check karke is secure link par click karein: {link}"
    )
}


def generate_outreach_message(
    name: str,
    amount_paise: int,
    failure_class: FailureClass,
    payment_link: str,
    error_description: str = None
) -> str:
    """Generates outreach text. Falls back to static template if OpenAI is disabled/fails."""
    amount_rupees = amount_paise / 100.0
    customer_name = name or "Customer"

    # Default rule-based template
    template = OUTREACH_TEMPLATES.get(failure_class, OUTREACH_TEMPLATES[FailureClass.UNKNOWN])
    default_message = template.format(name=customer_name, amount=amount_rupees, link=payment_link)

    # If OpenAI API is enabled, generate via LLM for maximum personalization
    if settings.USE_LLM_EXPLANATIONS and settings.OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            prompt = (
                f"Create a friendly customer notification message in Hinglish (Hindi written in English script) to recover a failed payment.\n"
                f"- Customer Name: {customer_name}\n"
                f"- Payment Amount: Rs. {amount_rupees:.2f}\n"
                f"- Failure Reason Category: {failure_class.value}\n"
                f"- Failure Description details: {error_description or 'None'}\n"
                f"- Recovery Checkout Link: {payment_link}\n\n"
                f"Requirements:\n"
                f"1. Be extremely polite, helpful and direct.\n"
                f"2. Clearly reference the checkout link: {payment_link}\n"
                f"3. Explain the error simply in conversational Hinglish (e.g. 'UPI app timeout ho gaya' or 'decline kiya bank ne').\n"
                f"4. Length must be short (maximum 2-3 sentences)."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a customer success specialist writing friendly Hinglish text outreach templates."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.7
            )
            outreach = response.choices[0].message.content.strip()
            if outreach and payment_link in outreach:
                return outreach
        except Exception as e:
            print(f"[Outreach] LLM message generation failed: {e}. Falling back to default template.")

    return default_message
