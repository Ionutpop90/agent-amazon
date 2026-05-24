import pandas as pd

data = {
    'review': [
        'Produsul s-a stricat dupa 2 saptamani',
        'Calitate excelenta, recomand!',
        'Livrarea a intarziat 5 zile',
        'Exact cum era descris, multumit',
        'Materialul e ieftin, dezamagit',
        'Nu functioneaza cum e descris',
        'Super produs, cumpar din nou',
        'S-a rupt dupa prima utilizare',
        'Bateria se descarca in 2 ore, dezamagitor',
        'Nu merita pretul, calitate slaba',
        'S-a deformat dupa prima spalare',
        'Exact ce cautam, foarte multumit',
        'Recomand cu incredere, super calitate'
    ],
    'rating': [1, 5, 2, 4, 2, 1, 5, 1, 1, 1, 2, 5, 5],
    'verified': [True, True, False, True, True, True, False, True, True, True, True, True, True]
}
print(f"Reviewuri: {len(data['review'])}")
print(f"Ratinguri: {len(data['rating'])}")
print(f"Verified: {len(data['verified'])}")
df = pd.DataFrame(data)

print("=== STATISTICI GENERALE ===")
print(f"Total reviews: {len(df)}")
print(f"Rating mediu: {df['rating'].mean():.2f}")
print(f"Reviews negative (1-2 stele): {len(df[df['rating'] <= 3])}")                                       
# Task 2 - Salveaza reviewurile negative
negative_reviews = df[df['rating'] <= 3]
negative_reviews.to_csv('negative_reviews.csv', index=False)
print(f"\nFisier salvat cu {len(negative_reviews)} reviewuri negative!")
text_test = "produsul e slab si ieftin"
cuvinte = text_test.split()
print(cuvinte)
# Cuvinte pe care le ignoram
stop_words = ['e', 'si', 'a', 'de', 'la', 'cu', 'nu', 'in', 'ca', 'cum', 'dupa', 's-a', 'prima', '2']

# Filtram cuvintele mici
cuvinte_utile = [c for c in cuvinte if c not in stop_words]
print(cuvinte_utile)
# Numaram aparitiile fiecarui cuvant
from collections import Counter
numarator = Counter(cuvinte_utile)
print(numarator)
toate_cuvintele = []
for review in negative_reviews['review']:
    cuvinte = review.lower().split()
    for cuvant in cuvinte:
        if cuvant not in stop_words:
            toate_cuvintele.append(cuvant)
top5 = Counter(toate_cuvintele).most_common(5)
print("\n=== TOP5 PROBLEME DIN REVOEWURI NEGATIVE ===")
for cuvant, count in top5:
    print(f" '{cuvant}': apare de {count} ori")

    
                                        
