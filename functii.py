# O functie e ca o reteta - o scrii o data, o folosesti de ori cate ori vrei

def saluta(nume):
    mesaj = f"Buna ziua, {nume}!"
    return mesaj

# Apelam functia
print(saluta("Ionut"))
print(saluta("Maria"))
print(saluta("Amazon Seller"))
# Functie cu 2 parametri
def calculeaza_pret(pret, discount):
    pret_final = pret - (pret * discount / 100)
    return pret_final

print(calculeaza_pret(100, 10))  # 100 euro cu 10% discount
print(calculeaza_pret(50, 20))   # 50 euro cu 20% discount
import anthropic

client = anthropic.Anthropic(api_key="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")

def analizeaza_review(review, produs):
    mesaj = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[
            {"role": "user", "content": f"Problema principala din acest review pentru '{produs}' in maxim 1 rand: '{review}'"}
        ]
    )
    return mesaj.content[0].text

# Testam functia
rezultat = analizeaza_review("Nu e compatibil cu dusul meu", "Filtro TRICAPA")
print(rezultat)
def calculeaza_acos(vanzari, cheltuieli):
    acos = (cheltuieli / vanzari) * 100
    return acos
print(calculeaza_acos(1000, 150))
print(calculeaza_acos(500, 200))