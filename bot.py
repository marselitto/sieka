import os
import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import re

# Konfiguracja bota
TOKEN = os.getenv('DISCORD_TOKEN')  # Token bota - ustaw w zmiennych środowiskowych
PREFIX = '!'
INTERVAL = 15  # Czas między sprawdzeniami w minutach

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Przechowywanie konfiguracji użytkowników
user_configs = {}
seen_offers = set()

class OLXScraper:
    @staticmethod
    def parse_price(price_text):
        if not price_text:
            return "Cena nie podana"
        # Usunięcie zbędnych znaków i konwersja na liczbę
        price_clean = re.sub(r'[^\d,]', '', price_text).replace(',', '.')
        try:
            return price_text.strip()
        except:
            return price_text.strip()
    
    @staticmethod
    def search_olx(query, category=None, min_price=None, max_price=None):
        url = f"https://www.olx.pl/oferty/q-{query.replace(' ', '-')}/"
        
        if category:
            url = f"https://www.olx.pl/{category}/q-{query.replace(' ', '-')}/"
        
        params = {}
        if min_price:
            params['search[filter_float_price:from]'] = min_price
        if max_price:
            params['search[filter_float_price:to]'] = max_price
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            response = requests.get(url, params=params, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            offers = []
            offer_elements = soup.find_all('div', {'data-cy': 'l-card'})
            
            for offer in offer_elements[:5]:  # Pobieramy tylko 5 najnowszych ofert
                try:
                    title_element = offer.find('h6')
                    title = title_element.text.strip() if title_element else "Brak tytułu"
                    
                    url_element = offer.find('a')
                    offer_url = url_element['href'] if url_element else ""
                    if not offer_url.startswith('http'):
                        offer_url = 'https://www.olx.pl' + offer_url
                    
                    price_element = offer.find('p', {'data-testid': 'ad-price'}) 
                    price = OLXScraper.parse_price(price_element.text) if price_element else "Cena nie podana"
                    
                    img_element = offer.find('img')
                    img_url = img_element['src'] if img_element and 'src' in img_element.attrs else ""
                    
                    offer_id = re.search(r'ID(.+?)$', offer_url)
                    if not offer_id:
                        offer_id = offer_url  # Jeśli nie możemy wyciągnąć ID, używamy całego URL jako ID
                    else:
                        offer_id = offer_id.group(1)
                    
                    offers.append({
                        'id': offer_id,
                        'title': title,
                        'price': price,
                        'url': offer_url,
                        'img_url': img_url
                    })
                except Exception as e:
                    print(f"Błąd podczas parsowania oferty: {e}")
            
            return offers
        except Exception as e:
            print(f"Błąd podczas wyszukiwania: {e}")
            return []

@bot.event
async def on_ready():
    print(f'Bot zalogowany jako {bot.user.name}')
    check_offers.start()
    clear_old_offers.start()  # Uruchamiamy zadanie czyszczenia po zalogowaniu bota

@bot.command(name='monitor')
async def monitor(ctx, *, params):
    """
    Dodaje nowe monitorowanie OLX. 
    Użycie: !monitor szukane_frazy | [kategoria] | [min_cena] | [max_cena]
    Przykład: !monitor iPhone 13 | elektronika | 2000 | 3500
    """
    parts = [part.strip() for part in params.split('|')]
    
    query = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    min_price = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    max_price = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
    
    if not query:
        await ctx.send("❌ Musisz podać co najmniej frazę wyszukiwania!")
        return
    
    user_id = str(ctx.author.id)
    channel_id = ctx.channel.id
    
    config = {
        'query': query,
        'category': category,
        'min_price': min_price,
        'max_price': max_price,
        'channel_id': channel_id
    }
    
    if user_id not in user_configs:
        user_configs[user_id] = []
    
    user_configs[user_id].append(config)
    
    await ctx.send(f"✅ Dodano monitorowanie dla: **{query}**\n"
                  f"Kategoria: {category or 'wszystkie'}\n"
                  f"Zakres cen: {min_price or 'od min'} - {max_price or 'do max'} zł\n"
                  f"Powiadomienia będą wysyłane do tego kanału co {INTERVAL} minut.")

@bot.command(name='lista')
async def list_monitors(ctx):
    """Wyświetla listę monitorowanych wyszukiwań"""
    user_id = str(ctx.author.id)
    
    if user_id not in user_configs or not user_configs[user_id]:
        await ctx.send("❌ Nie masz żadnych monitorowanych wyszukiwań.")
        return
    
    embed = discord.Embed(
        title="📋 Twoje monitorowane wyszukiwania",
        color=discord.Color.blue()
    )
    
    for i, config in enumerate(user_configs[user_id], 1):
        value = f"Kategoria: {config['category'] or 'wszystkie'}\n" \
                f"Cena: {config['min_price'] or 'min'} - {config['max_price'] or 'max'} zł"
        embed.add_field(
            name=f"{i}. {config['query']}",
            value=value,
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='usun')
async def remove_monitor(ctx, index: int):
    """Usuwa monitorowane wyszukiwanie o podanym indeksie"""
    user_id = str(ctx.author.id)
    
    if user_id not in user_configs or not user_configs[user_id]:
        await ctx.send("❌ Nie masz żadnych monitorowanych wyszukiwań.")
        return
    
    if index < 1 or index > len(user_configs[user_id]):
        await ctx.send(f"❌ Nieprawidłowy indeks. Wybierz od 1 do {len(user_configs[user_id])}.")
        return
    
    removed = user_configs[user_id].pop(index - 1)
    await ctx.send(f"✅ Usunięto monitorowanie dla: **{removed['query']}**")

@bot.command(name='pomoc')
async def help_command(ctx):
    """Wyświetla dostępne komendy"""
    embed = discord.Embed(
        title="📚 Pomoc - OLX Monitor Bot",
        description="Lista dostępnych komend:",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name=f"{PREFIX}monitor <fraza> | [kategoria] | [min_cena] | [max_cena]",
        value="Dodaje nowe monitorowanie OLX\n"
              "Przykład: `!monitor iPhone 13 | elektronika | 2000 | 3500`",
        inline=False
    )
    
    embed.add_field(
        name=f"{PREFIX}lista",
        value="Wyświetla listę twoich monitorowanych wyszukiwań",
        inline=False
    )
    
    embed.add_field(
        name=f"{PREFIX}usun <numer>",
        value="Usuwa monitorowane wyszukiwanie o podanym numerze z listy\n"
              "Przykład: `!usun 1`",
        inline=False
    )
    
    embed.add_field(
        name=f"{PREFIX}pomoc",
        value="Wyświetla tę wiadomość",
        inline=False
    )
    
    await ctx.send(embed=embed)

@tasks.loop(minutes=INTERVAL)
async def check_offers():
    """Sprawdza nowe oferty dla wszystkich monitorowanych wyszukiwań"""
    print(f"[{datetime.now()}] Sprawdzanie nowych ofert...")
    for user_id, configs in user_configs.items():
        for config in configs:
            try:
                offers = OLXScraper.search_olx(
                    config['query'],
                    category=config['category'],
                    min_price=config['min_price'],
                    max_price=config['max_price']
                )
                
                channel = bot.get_channel(config['channel_id'])
                if not channel:
                    print(f"Nie można znaleźć kanału o ID {config['channel_id']}")
                    continue
                
                new_offers = []
                for offer in offers:
                    offer_key = f"{user_id}_{offer['id']}"
                    if offer_key not in seen_offers:
                        seen_offers.add(offer_key)
                        new_offers.append(offer)
                
                for offer in new_offers:
                    embed = discord.Embed(
                        title=offer['title'],
                        url=offer['url'],
                        color=discord.Color.blue(),
                        description=f"💰 **Cena:** {offer['price']}"
                    )
                    
                    if offer['img_url']:
                        embed.set_thumbnail(url=offer['img_url'])
                    
                    embed.set_footer(text=f"Wyszukiwanie: {config['query']}")
                    
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Błąd podczas sprawdzania ofert: {e}")

# Limit ilości zapamiętanych ofert aby uniknąć wycieków pamięci
@tasks.loop(hours=24)
async def clear_old_offers():
    """Czyści starsze oferty z pamięci"""
    global seen_offers
    if len(seen_offers) > 10000:
        seen_offers = set(list(seen_offers)[-5000:])
    print(f"[{datetime.now()}] Wyczyszczono pamięć ofert. Pozostało {len(seen_offers)} ofert.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Nieznana komenda. Użyj `{PREFIX}pomoc` aby zobaczyć dostępne komendy.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Brakujący argument. Użyj `{PREFIX}pomoc` aby zobaczyć poprawne użycie.")
    else:
        await ctx.send(f"❌ Wystąpił błąd: {error}")
        print(f"Błąd: {error}")

# Uruchomienie bota
if __name__ == "__main__":
    # Zadanie clear_old_offers zostanie uruchomione automatycznie po uruchomieniu bota
    # dzięki dekoratorowi @tasks.loop
    bot.run(TOKEN)
