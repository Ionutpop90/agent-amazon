import anthropic

client = anthropic.Anthropic(api_key="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")

mesaj = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    messages=[
     {"role": "user", "content": "Analizeaza acest review negativ si spune care e problema principala: 'Produsul s-a stricat dupa 2 saptamani, materialul e ieftin'"}
    ]
)

print(mesaj.content[0].text)