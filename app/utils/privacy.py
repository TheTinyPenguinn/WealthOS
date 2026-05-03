import re


def sanitise_for_ai(text: str) -> str:
    text = re.sub(r"\b\d{8,16}\b", lambda m: "XXXX" + m.group()[-4:], text)
    text = re.sub(r"[A-Z]{5}[0-9]{4}[A-Z]", "[PAN]", text)
    text = re.sub(r"[\w.-]+@[\w]+", "[UPI]", text)
    text = re.sub(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "[AADHAAR]", text)
    text = re.sub(r"\b[6-9]\d{9}\b", "[PHONE]", text)
    return text
