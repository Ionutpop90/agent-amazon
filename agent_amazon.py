import anthropic
import pandas as pd

# Conexiunea cu Claude
client = anthropic.Anthropic(api_key="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")

# Datele produselor tale Casa Donostia
produse = [
    {"nume": "Filtro TRICAPA", "vanzari": 500, "cheltuieli": 150, "rating": 3.7},
    {"nume": "Alcachofa Negra", "vanzari": 800, "cheltuieli": 200, "rating": 4.5},
    {"nume": "Alcachofa Cromo", "vanzari": 600, "cheltuieli": 180, "rating": 4.5},
]

print("Agent Amazon pornit!")
print(f"Produse de analizat: {len(produse)}")
# Functia 1 - Calculeaza ACOS
def calculeaza_acos(vanzari, cheltuieli):
    return (cheltuieli / vanzari) * 100

# Functia 2 - Evalueaza situatia produsului
def evalueaza_produs(produs):
    acos = calculeaza_acos(produs['vanzari'], produs['cheltuieli'])
    
    if acos < 20:
        status = "EXCELENT"
    elif acos < 35:
        status = "BUN"
    else:
        status = "ATENTIE - ACOS prea mare"
    
    return acos, status

# Analizam fiecare produs
print("\n=== RAPORT CASA DONOSTIA ===")
for produs in produse:
    acos, status = evalueaza_produs(produs)
    print(f"{produs['nume']}: ACOS {acos:.1f}% — {status} | Rating: {produs['rating']}")
    # Functia 3 - Claude recomanda actiuni pentru produse cu rating slab
def recomanda_actiuni(produs, acos):
    mesaj = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[
            {"role": "user", "content": f"Esti expert Amazon. Produsul '{produs['nume']}' are rating {produs['rating']} si ACOS {acos:.1f}%. Da 2 actiuni concrete si scurte pentru a imbunatati performanta."}
        ]
    )
    return mesaj.content[0].text

# Verificam produsele cu rating sub 4.0
print("\n=== PRODUSE CU PROBLEME ===")
for produs in produse:
    if produs['rating'] < 4.0:
        acos, status = evalueaza_produs(produs)
        recomandare = recomanda_actiuni(produs, acos)
        print(f"\nProdus: {produs['nume']}")
        print(f"Recomandare Claude: {recomandare}")