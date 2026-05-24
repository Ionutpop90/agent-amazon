import pandas as pd
import anthropic
# Conexiune cu CLaude 
client = anthropic.Anthropic(api_key="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")
#Citim CSV-UL cu reviewuri
df = pd.read_csv('reviews_reale.csv')
print(f"total reviewuri incarcate: {len(df)}")
print(df.head())
# Filtram doar reviewurile negative
negative = df[df['rating'] <= 2]
print(f"\nReviewuri negative: {len(negative)}")

# Claude analizeaza fiecare
rezultate = []
for index, row in negative.iterrows():
    mesaj = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {"role": "user", "content": f"Analizeaza acest review negativ pentru produsul '{row['produs']}' si sugereaza o solutie concreta in 2 randuri: '{row['review']}'"}
        ]
    )
    rezultate.append({
        'produs': row['produs'],
        'review': row['review'],
        'analiza': mesaj.content[0].text
    })
    print(f"\nProdus: {row['produs']}")
    print(f"Analiza: {mesaj.content[0].text}")

# Salvam raportul
raport = pd.DataFrame(rezultate)
raport.to_csv('raport_final.csv', index=False)
print("\nRaport salvat in raport_final.csv!")