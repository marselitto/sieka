import os
import discord
from discord.ext import commands, tasks
from discord import ButtonStyle, app_commands
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import re

# Konfiguracja bota
TOKEN = os.getenv('DISCORD_TOKEN')  # Token bota - ustaw w zmiennych środowiskowych
PREFIX = '!'
INTERVAL = 5  # Czas między sprawdzeniami w minutach

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
    def search_olx(query, category=None, min_price=None, max_price=None, delivery_option=None, condition=None, location=None, sort_by='newest'):
        url = f"https://www.olx.pl/oferty/q-{query.replace(' ', '-')}/"
        
        if category:
            url = f"https://www.olx.pl/{category}/q-{query.replace(' ', '-')}/"
        
        params = {}
        
        # Dodanie parametru sortowania - domyślnie według najnowszych
        if sort_by == 'newest':
            params['search[order]'] = 'created_at:desc'
        
        if min_price:
            params['search[filter_float_price:from]'] = min_price
        if max_price:
            params['search[filter_float_price:to]'] = max_price
        
        # Dodanie filtra wysyłki OLX
        if delivery_option == "olx":
            params['search[filter_enum_shipping][0]'] = 'olx'
        elif delivery_option == "free":
            params['search[filter_enum_free_shipping]'] = 1
            
        # Dodanie filtra stanu przedmiotu
        if condition:
            condition_map = {
                "nowy": "new",
                "używany": "used",
                "uszkodzony": "damaged"
            }
            if condition in condition_map:
                params['search[filter_enum_state][0]'] = condition_map[condition]
                
        # Dodanie filtra lokalizacji
        if location:
            params['search[city_id]'] = location  # Wymaga ID miasta z OLX
            
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
                    # Poprawione pobieranie tytułu - szukamy różnych elementów
                    title_element = offer.find('h6')
                    if not title_element:
                        title_element = offer.find('a').find('h6')
                    if not title_element:
                        title_element = offer.find('a').find('div', {'data-testid': 'listing-ad-title'})
                    if not title_element:
                        all_headings = offer.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                        if all_headings:
                            title_element = all_headings[0]
                            
                    title = title_element.text.strip() if title_element else "Brak tytułu"
                    
                    url_element = offer.find('a')
                    offer_url = url_element['href'] if url_element else ""
                    if not offer_url.startswith('http'):
                        offer_url = 'https://www.olx.pl' + offer_url
                    
                    price_element = offer.find('p', {'data-testid': 'ad-price'}) 
                    price = OLXScraper.parse_price(price_element.text) if price_element else "Cena nie podana"
                    
                    img_element = offer.find('img')
                    img_url = img_element['src'] if img_element and 'src' in img_element.attrs else ""
                    
                    # Dodanie informacji o wysyłce
                    delivery_info = "Brak informacji"
                    delivery_element = offer.find('span', {'data-testid': 'delivery-icon'})
                    if delivery_element:
                        delivery_info = "Wysyłka OLX"
                    
                    # Poprawiona linia z błędem:
                    offer_id = re.search(r'ID(.+?)', offer_url)
                    if not offer_id:
                        offer_id = offer_url  # Jeśli nie możemy wyciągnąć ID, używamy całego URL jako ID
                    else:
                        offer_id = offer_id.group(1)
                    
                    location_element = offer.find('p', {'data-testid': 'location-date'})
                    location_text = location_element.text.strip() if location_element else "Brak lokalizacji"
                    
                    offers.append({
                        'id': offer_id,
                        'title': title,
                        'price': price,
                        'url': offer_url,
                        'img_url': img_url,
                        'delivery': delivery_info,
                        'location': location_text
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

@bot.event
async def on_interaction(interaction):
    # Obsługa interakcji z przyciskami
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get('custom_id', '')
        
        # Obsługa przycisku usuwania monitorowania
        if custom_id.startswith('remove_monitor_'):
            try:
                parts = custom_id.split('_')
                monitor_index = int(parts[2])
                user_id = parts[3]
                
                # Sprawdzenie czy użytkownik ma uprawnienia do usunięcia
                if str(interaction.user.id) == user_id:
                    if user_id in user_configs and 0 <= monitor_index < len(user_configs[user_id]):
                        removed = user_configs[user_id].pop(monitor_index)
                        await interaction.response.send_message(f"✅ Usunięto monitorowanie dla: **{removed['query']}**", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ Nie znaleziono tego monitorowania.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Nie masz uprawnień do usunięcia tego monitorowania.", ephemeral=True)
            except Exception as e:
                print(f"Błąd podczas usuwania monitorowania: {e}")
                await interaction.response.send_message("❌ Wystąpił błąd.", ephemeral=True)
        
        # Obsługa przycisku dodawania nowego monitorowania
        elif custom_id == "add_monitor_button":
            # Tworzymy klasę modalu do zbierania danych
            class MonitorModal(discord.ui.Modal):
                def __init__(self):
                    super().__init__(title="Dodaj nowe monitorowanie OLX")
                    
                    self.query = discord.ui.TextInput(
                        label="Szukana fraza",
                        style=discord.TextStyle.short,
                        placeholder="np. iPhone 13",
                        required=True
                    )
                    
                    self.category = discord.ui.TextInput(
                        label="Kategoria (opcjonalnie)",
                        style=discord.TextStyle.short,
                        placeholder="np. elektronika",
                        required=False
                    )
                    
                    self.min_price = discord.ui.TextInput(
                        label="Minimalna cena (opcjonalnie)",
                        style=discord.TextStyle.short,
                        placeholder="np. 1000",
                        required=False
                    )
                    
                    self.max_price = discord.ui.TextInput(
                        label="Maksymalna cena (opcjonalnie)",
                        style=discord.TextStyle.short,
                        placeholder="np. 3000",
                        required=False
                    )
                    
                    self.delivery = discord.ui.TextInput(
                        label="Opcje wysyłki (olx/free/brak)",
                        style=discord.TextStyle.short,
                        placeholder="np. olx",
                        required=False
                    )
                    
                    # Dodajemy pola do modalu
                    self.add_item(self.query)
                    self.add_item(self.category)
                    self.add_item(self.min_price)
                    self.add_item(self.max_price)
                    self.add_item(self.delivery)
                
                async def on_submit(self, interaction: discord.Interaction):
                    # Przetwarzanie danych z formularza
                    query = self.query.value
                    category = self.category.value if self.category.value else None
                    min_price = self.min_price.value if self.min_price.value else None
                    max_price = self.max_price.value if self.max_price.value else None
                    delivery = self.delivery.value.lower() if self.delivery.value else None
                    
                    user_id = str(interaction.user.id)
                    channel_id = interaction.channel.id
                    
                    config = {
                        'query': query,
                        'category': category,
                        'min_price': min_price,
                        'max_price': max_price,
                        'delivery': delivery,
                        'channel_id': channel_id,
                        'sort_by': 'newest'  # Domyślnie sortujemy po najnowszych
                    }
                    
                    if user_id not in user_configs:
                        user_configs[user_id] = []
                    
                    user_configs[user_id].append(config)
                    
                    # Przygotowanie informacji o opcjach wysyłki
                    delivery_info = ""
                    if delivery:
                        if delivery == "olx":
                            delivery_info = "Tylko z wysyłką OLX"
                        elif delivery == "free":
                            delivery_info = "Tylko z darmową wysyłką"
                    
                    # Tworzenie przycisku do usunięcia monitorowania
                    view = discord.ui.View()
                    button = discord.ui.Button(
                        label="Usuń monitorowanie", 
                        style=discord.ButtonStyle.danger, 
                        custom_id=f"remove_monitor_{len(user_configs[user_id])-1}_{user_id}"
                    )
                    view.add_item(button)
                    
                    await interaction.response.send_message(
                        f"✅ Dodano monitorowanie dla: **{query}**\n"
                        f"Kategoria: {category or 'wszystkie'}\n"
                        f"Zakres cen: {min_price or 'od min'} - {max_price or 'do max'} zł\n"
                        f"{delivery_info}\n"
                        f"Sortowanie: Według najnowszych\n"
                        f"Powiadomienia będą wysyłane do tego kanału co {INTERVAL} minut.",
                        view=view
                    )
            
            # Wysyłamy modal do użytkownika
            await interaction.response.send_modal(MonitorModal())
            
        # Obsługa przycisku wyświetlania listy monitorowań
        elif custom_id == "list_monitors_button":
            user_id = str(interaction.user.id)
            
            if user_id not in user_configs or not user_configs[user_id]:
                await interaction.response.send_message("❌ Nie masz żadnych monitorowanych wyszukiwań.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📋 Twoje monitorowane wyszukiwania",
                color=discord.Color.blue()
            )
            
            for i, config in enumerate(user_configs[user_id], 1):
                # Przygotowanie informacji o opcjach wysyłki
                delivery_info = ""
                if config.get('delivery'):
                    if config['delivery'] == "olx":
                        delivery_info = "Tylko z wysyłką OLX"
                    elif config['delivery'] == "free":
                        delivery_info = "Tylko z darmową wysyłką"
                
                value = f"Kategoria: {config['category'] or 'wszystkie'}\n" \
                        f"Cena: {config['min_price'] or 'min'} - {config['max_price'] or 'max'} zł\n" \
                        f"{delivery_info}\n" \
                        f"Sortowanie: Według najnowszych"
                embed.add_field(
                    name=f"{i}. {config['query']}",
                    value=value,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command(name='monitor')
async def monitor(ctx, *, params):
    """
    Dodaje nowe monitorowanie OLX. 
    Użycie: !monitor szukane_frazy | [kategoria] | [min_cena] | [max_cena] | [opcje_wysyłki] | [stan] | [lokalizacja]
    Przykład: !monitor iPhone 13 | elektronika | 2000 | 3500 | olx | nowy | Warszawa
    """
    parts = [part.strip() for part in params.split('|')]
    
    query = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    min_price = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    max_price = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
    delivery = parts[4].strip().lower() if len(parts) > 4 and parts[4].strip() else None
    condition = parts[5].strip().lower() if len(parts) > 5 and parts[5].strip() else None
    location = parts[6].strip() if len(parts) > 6 and parts[6].strip() else None
    
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
        'delivery': delivery,
        'condition': condition,
        'location': location,
        'channel_id': channel_id,
        'sort_by': 'newest'  # Domyślnie sortujemy po najnowszych
    }
    
    if user_id not in user_configs:
        user_configs[user_id] = []
    
    user_configs[user_id].append(config)
    
    # Przygotowanie informacji o opcjonalnych filtrach
    delivery_info = ""
    if delivery:
        if delivery == "olx":
            delivery_info = "Tylko z wysyłką OLX"
        elif delivery == "free":
            delivery_info = "Tylko z darmową wysyłką"
    
    condition_info = ""
    if condition:
        condition_display = {"nowy": "Nowy", "używany": "Używany", "uszkodzony": "Uszkodzony"}.get(condition, condition)
        condition_info = f"Stan: {condition_display}"
    
    location_info = f"Lokalizacja: {location}" if location else ""
    
    # Tworzenie przycisku do usunięcia monitorowania
    view = discord.ui.View()
    button = discord.ui.Button(label="Usuń monitorowanie", style=discord.ButtonStyle.danger, custom_id=f"remove_monitor_{len(user_configs[user_id])-1}_{user_id}")
    view.add_item(button)
    
    await ctx.send(
        f"✅ Dodano monitorowanie dla: **{query}**\n"
        f"Kategoria: {category or 'wszystkie'}\n"
        f"Zakres cen: {min_price or 'od min'} - {max_price or 'do max'} zł\n"
        f"{delivery_info}\n{condition_info}\n{location_info}\n"
        f"Sortowanie: Według najnowszych\n"
        f"Powiadomienia będą wysyłane do tego kanału co {INTERVAL} minut.",
        view=view
    )

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
        # Przygotowanie informacji o opcjach wysyłki
        delivery_info = ""
        if config.get('delivery'):
            if config['delivery'] == "olx":
                delivery_info = "Tylko z wysyłką OLX"
            elif config['delivery'] == "free":
                delivery_info = "Tylko z darmową wysyłką"
        
        value = f"Kategoria: {config['category'] or 'wszystkie'}\n" \
                f"Cena: {config['min_price'] or 'min'} - {config['max_price'] or 'max'} zł\n" \
                f"{delivery_info}\n" \
                f"Sortowanie: Według najnowszych"
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
        name=f"{PREFIX}monitor <fraza> | [kategoria] | [min_cena] | [max_cena] | [opcje_wysyłki] | [stan] | [lokalizacja]",
        value="Dodaje nowe monitorowanie OLX\n"
              "Przykład: `!monitor iPhone 13 | elektronika | 2000 | 3500 | olx | nowy | Warszawa`\n"
              "Opcje wysyłki: `olx` (tylko z wysyłką OLX), `free` (darmowa wysyłka)\n"
              "Stan: `nowy`, `używany`, `uszkodzony`\n"
              "Sortowane wg. najnowszych ofert",
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
    
    # Dodanie przycisków do interakcji
    view = discord.ui.View()
    
    # Przycisk do dodania nowego monitorowania
    button_add = discord.ui.Button(
        label="Dodaj nowe monitorowanie", 
        style=discord.ButtonStyle.primary, 
        custom_id="add_monitor_button"
    )
    view.add_item(button_add)
    
    # Przycisk do wyświetlenia listy
    button_list = discord.ui.Button(
        label="Pokaż listę monitorowań", 
        style=discord.ButtonStyle.secondary, 
        custom_id="list_monitors_button"
    )
    view.add_item(button_list)
    
    await ctx.send(embed=embed, view=view)

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
                    max_price=config['max_price'],
                    delivery_option=config.get('delivery'),
                    condition=config.get('condition'),
                    location=config.get('location'),
                    sort_by=config.get('sort_by', 'newest')  # Domyślnie sortowanie wg najnowszych
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
                    
                    # Dodanie informacji o dostawie i lokalizacji
                    if 'delivery' in offer:
                        embed.add_field(name="📦 Dostawa", value=offer['delivery'], inline=True)
                    
                    if 'location' in offer:
                        embed.add_field(name="📍 Lokalizacja", value=offer['location'], inline=True)
                    
                    embed.set_footer(text=f"Wyszukiwanie: {config['query']}")
                    
                    # Tworzenie przycisków
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="Zobacz ofertę", 
                        style=discord.ButtonStyle.link, 
                        url=offer['url']
                    ))
                    
                    await channel.send(embed=embed, view=view)
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
