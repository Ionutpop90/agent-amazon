import anthropic

client = anthropic.Anthropic(api_key="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")

# Reviewurile negative
reviews_negative = [
    "Produsul s-a stricat dupa 2 saptamani, materialul e ieftin",
    "Livrarea a intarziat 5 zile",
    "Nu functioneaza cum e descris",
    "S-a rupt dupa prima utilizare",
    "Bateria se descarca in 2 ore, dezamagitor"
]

# Analizam fiecare review
for review in reviews_negative:
    mesaj = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {"role": "user", "content": f"Problema principala din acest review in maxim 2 randuri: '{review}'"}
        ]
    )
    print(f"Review: {review}")
    print(f"Analiza: {mesaj.content[0].text}")
    print("---")