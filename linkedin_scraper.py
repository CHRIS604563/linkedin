import sys
sys.stdout.reconfigure(line_buffering=True)  # For render logs

import requests
from bs4 import BeautifulSoup
import time
import json
import os
import re
from datetime import datetime
from urllib.parse import urlencode
import random

class LinkedInJobScraper:
    def __init__(self, search_keywords, locations, telegram_bot_token="", telegram_chat_id=""):
        self.keywords = search_keywords
        self.locations = locations
        self.bot_token = telegram_bot_token
        self.chat_id = telegram_chat_id
        self.seen_jobs = self.load_seen_jobs()
        self.session = requests.Session()
        
    def get_headers(self):
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        
        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
    
    def is_truly_remote(self, titulo: str, local: str, search_location: str) -> bool:
        """
        FILTRO BRUTAL - retorna True APENAS se for REALMENTE remoto
        """
        titulo_lower = titulo.lower()
        local_lower = local.lower()
        search_lower = search_location.lower()
        
        # Se a busca NÃO é por remote, aceitar tudo
        if 'remote' not in search_lower and 'remoto' not in search_lower:
            return True
        
        # AGORA A BUSCA É POR REMOTE - FILTRAR COM FORÇA
        
        # BLACKLIST - Se tiver QUALQUER uma dessas, NÃO É REMOTO
        palavras_nao_remoto = [
            'on-site', 'onsite', 'on site',
            'presencial', 'in-office', 'office based',
            'escritorio', 'escritório',
            'local', 'sede',
            # Cidades específicas que indicam presencial
            'sao paulo, sp', 'rio de janeiro, rj', 'belo horizonte',
            'salvador, ba', 'brasilia, df', 'curitiba',
            'porto alegre', 'fortaleza', 'recife',
            # Padrões de endereço
            ', sp', ', rj', ', mg', ', ba', ', df', ', pr', ', rs', ', ce', ', pe',
            'avenida', 'rua ', 'av.', 'r.'
        ]
        
        for palavra in palavras_nao_remoto:
            if palavra in local_lower or palavra in titulo_lower:
                return False
        
        # WHITELIST - Aceitar APENAS se tiver uma dessas
        palavras_remoto_real = [
            'remote',
            'remoto',
            'home office',
            'home-office',
            'work from home',
            'wfh',
            'anywhere',
            '100% remote',
            'fully remote',
            'completamente remoto',
            'totalmente remoto',
            'trabalhe de casa',
            'de qualquer lugar'
        ]
        
        # Verificar se TEM palavra remota no local OU no título
        tem_palavra_remota = any(p in local_lower for p in palavras_remoto_real)
        tem_palavra_remota_titulo = any(p in titulo_lower for p in palavras_remoto_real)
        
        if not (tem_palavra_remota or tem_palavra_remota_titulo):
            return False
        
        # VERIFICAÇÃO ADICIONAL: Se tem "Remote in [cidade]", é SUSPEITO
        # Exemplo: "Remote in São Paulo" = provavelmente híbrido disfarçado
        if 'remote in' in local_lower or 'remoto em' in local_lower:
            # Se menciona cidade específica, REJEITAR
            cidades_br = [
                'paulo', 'janeiro', 'horizonte', 'salvador', 'brasilia',
                'curitiba', 'alegre', 'fortaleza', 'recife', 'goiania',
                'belem', 'manaus', 'maranhao', 'luis'
            ]
            if any(cidade in local_lower for cidade in cidades_br):
                return False
        
        # Se passou por tudo, É REMOTO
        return True
    
    def keywords_match(self, titulo: str, keyword: str) -> bool:
        """Verifica se o título é relevante para TI/Suporte"""
        titulo_lower = titulo.lower()
        keyword_lower = keyword.lower()
        
        palavras_ti = [
            'ti', 'informatica', 'tecnologia', 'suporte', 'help desk', 'helpdesk',
            'tecnico', 'technical', 'support', 'it', 'assistente', 'auxiliar',
            'analista', 'infra', 'redes', 'sistemas', 'computador', 'software',
            'hardware', 'service desk', 'field support', 'desktop', 'nivel 1',
            'nivel1', 'level 1', 'level1', 'junior', 'jr'
        ]
        
        palavras_erradas = [
            'vendas', 'sales', 'comercial', 'marketing', 'financeiro', 'finance',
            'rh', 'recursos humanos', 'hr', 'administrativo', 'recepcao',
            'motorista', 'entregador', 'delivery', 'limpeza', 'cozinha',
            'estoque', 'logistica', 'compras', 'contabil', 'juridico',
            'design', 'social media', 'conteudo', 'customer service',
            'administrative', 'executive', 'vendor'
        ]
        
        for p in palavras_erradas:
            if p in titulo_lower:
                return False
        
        if keyword_lower in titulo_lower:
            return True
        
        for p in palavras_ti:
            if p in titulo_lower:
                return True
        
        return False
    
    def detectar_idioma_titulo(self, titulo: str) -> str:
        titulo_lower = titulo.lower()
        
        palavras_pt_br = ['assistente', 'auxiliar', 'tecnico', 'suporte', 'analista']
        palavras_en = ['assistant', 'technician', 'support', 'analyst', 'it']
        
        score_pt = sum(1 for p in palavras_pt_br if p in titulo_lower)
        score_en = sum(1 for p in palavras_en if p in titulo_lower)
        
        tem_acento = any(c in titulo_lower for c in ['á', 'ã', 'â', 'é', 'ê', 'í', 'ó', 'ô', 'ú', 'ç'])
        if tem_acento:
            score_pt += 3
        
        return 'pt-br' if score_pt >= score_en else 'en'
    
    def load_seen_jobs(self):
        if os.path.exists('seen_jobs.json'):
            with open('seen_jobs.json', 'r') as f:
                return set(json.load(f))
        return set()
    
    def save_seen_jobs(self):
        with open('seen_jobs.json', 'w') as f:
            json.dump(list(self.seen_jobs), f)
    
    def scrape_jobs(self, keyword, location):
        if ',' in location:
            location = location.split(',')[0].strip()
        
        base_url = "https://www.linkedin.com/jobs/search"
        
        params = {
            'keywords': keyword,
            'location': location,
            'f_TPR': 'r86400',
            'position': 1,
            'pageNum': 0
        }
        
        # Se busca é por remote, adicionar filtro LinkedIn
        if 'remote' in location.lower() or 'remoto' in location.lower():
            params['f_WT'] = '2'  # Filtro remoto do LinkedIn
        
        url = f"{base_url}?{urlencode(params)}"
        
        try:
            headers = self.get_headers()
            response = self.session.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            job_cards = soup.find_all('div', {'class': re.compile(r'job-card|base-card|job-search-card')})
            
            if not job_cards:
                job_cards = soup.find_all('li', {'class': re.compile(r'job|result')})
            
            jobs = []
            for card in job_cards:
                try:
                    # Extrair título
                    title_elem = card.find('h3') or card.find('a', {'class': re.compile(r'title|link')})
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    
                    if not self.keywords_match(title, keyword):
                        continue
                    
                    # Extrair ID
                    job_id = card.get('data-job-id')
                    if not job_id:
                        link_elem = card.find('a', href=True)
                        if link_elem and '/jobs/view/' in link_elem['href']:
                            job_id = link_elem['href'].split('/jobs/view/')[-1].split('?')[0]
                    
                    if not job_id:
                        continue
                    
                    # Extrair empresa
                    company_elem = card.find('h4') or card.find('span', {'class': re.compile(r'company')})
                    company = company_elem.text.strip() if company_elem else 'N/A'
                    
                    # Extrair local
                    location_elem = card.find('span', {'class': re.compile(r'location')})
                    job_location = location_elem.text.strip() if location_elem else location
                    
                    # 🔥 FILTRO BRUTAL DE REMOTE
                    if not self.is_truly_remote(title, job_location, location):
                        continue  # SKIP vagas não-remotas
                    
                    # Extrair link
                    link_elem = card.find('a', href=True)
                    link = link_elem['href'] if link_elem else ''
                    if link and not link.startswith('http'):
                        link = 'https://www.linkedin.com' + link
                    
                    if job_id and job_id not in self.seen_jobs:
                        jobs.append({
                            'id': job_id,
                            'title': title,
                            'company': company,
                            'location': job_location,
                            'search_keyword': keyword,
                            'search_location': location,
                            'link': link
                        })
                        
                except Exception as e:
                    continue
            
            return jobs
            
        except Exception as e:
            return []
    
    def send_telegram(self, message):
        if not self.bot_token or not self.chat_id:
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        data = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False
        }
        
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except:
            return False
    
    def format_telegram_message(self, job):
        lang_icon = "🇧🇷" if self.detectar_idioma_titulo(job['title']) == 'pt-br' else "🇺🇸"
        
        # Se a busca foi por remote, é GARANTIDO remoto agora
        is_remote_search = 'remote' in job['search_location'].lower() or 'remoto' in job['search_location'].lower()
        
        msg = f"🚀 {lang_icon} <b>NOVA VAGA</b>\n\n"
        msg += f"<b>{job['title']}</b>\n"
        msg += f"🏢 {job['company']}\n"
        msg += f"📍 {job['location']}\n"
        
        if is_remote_search:
            msg += f"🏠✨ <b>100% REMOTO VERIFICADO</b>\n"
        
        msg += f"🔍 Keyword: {job['search_keyword']}\n\n"
        msg += f"<a href='{job['link']}'>📎 Ver vaga no LinkedIn</a>"
        
        if is_remote_search:
            msg += f"\n\n✨ <b>APLIQUE RÁPIDO!</b>"
        
        return msg
    
    def run(self):
        # Corrigir locations
        locations_corrigidas = []
        for loc in self.locations:
            if ',' in loc:
                loc = loc.split(',')[0].strip()
            locations_corrigidas.append(loc)
        self.locations = locations_corrigidas
        
        total_searches = len(self.keywords) * len(self.locations)
        
        # Separar buscas remotas de presenciais
        remote_locations = [l for l in self.locations if 'remote' in l.lower() or 'remoto' in l.lower()]
        local_locations = [l for l in self.locations if l not in remote_locations]
        
        print(f"\n{'='*60}")
        print(f"[*] LinkedIn Job Scraper - FILTRO REMOTO BRUTAL")
        print(f"[*] 📋 Filtrando vagas de TI/Suporte")
        print(f"[*] 🏠 APENAS remotas verdadeiras para buscas 'Remote'")
        print(f"[*] {len(self.keywords)} keywords × {len(self.locations)} locations")
        if remote_locations:
            print(f"[*] 🏠 Buscas remotas: {remote_locations}")
        if local_locations:
            print(f"[*] 📍 Buscas locais: {local_locations}")
        print(f"[*] Verificando a cada 5 minutos")
        print(f"{'='*60}\n")
        
        while True:
            try:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Verificando...")
                
                total_new = 0
                remote_new = 0
                count = 0
                
                for keyword in self.keywords:
                    for location in self.locations:
                        count += 1
                        is_remote_search = 'remote' in location.lower() or 'remoto' in location.lower()
                        
                        search_type = "🏠" if is_remote_search else "📍"
                        print(f"  [{count}/{total_searches}] {search_type} {keyword[:25]:25} em {location[:12]:12} ", end="", flush=True)
                        
                        jobs = self.scrape_jobs(keyword, location)
                        
                        if jobs:
                            print(f"→ {len(jobs)} vagas ✓")
                            total_new += len(jobs)
                            
                            if is_remote_search:
                                remote_new += len(jobs)
                            
                            for job in jobs:
                                msg = self.format_telegram_message(job)
                                self.send_telegram(msg)
                                self.seen_jobs.add(job['id'])
                                self.save_seen_jobs()
                                time.sleep(0.5)
                        else:
                            print("→ 0 ✗")
                        
                        time.sleep(random.uniform(2, 4))
                
                print(f"\n{'='*60}")
                print(f"[✓] Ciclo completo: {total_new} vagas relevantes")
                if remote_new > 0:
                    print(f"    🏠 Remotas verificadas: {remote_new}")
                print(f"[*] Próxima verificação em 5 minutos")
                print(f"{'='*60}\n")
                
                time.sleep(300)
                
            except KeyboardInterrupt:
                print("\n[*] Monitor interrompido")
                break
            except Exception as e:
                print(f"\n[!] Erro: {e}")
                time.sleep(60)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

SEARCH_KEYWORDS = [
    "Assistente de TI",
    "Assistente de Informatica",
    "Tecnico de Suporte",
    "Help Desk",
    "Suporte Nivel 1",
    "IT Support",
]

LOCATIONS = [
    "Maranhao",
    "Sao Luis", 
    "Remote",        # ← Vai filtrar BRUTAL - só remotas verdadeiras
    "Remoto"         # ← Idem
]

TELEGRAM_BOT_TOKEN = "8867079058:AAFGNaBdxEA83AGJaahjIsubpM3Pm0UL3vM"
TELEGRAM_CHAT_ID = "5430606426"

if __name__ == "__main__":
    scraper = LinkedInJobScraper(
        search_keywords=SEARCH_KEYWORDS,
        locations=LOCATIONS,
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID
    )
    
    scraper.run()
