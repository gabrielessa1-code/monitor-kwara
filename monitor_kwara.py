import html
import json
import os
import re
import time
import urllib.parse
import requests
from google import genai
from google.genai import types

ARQUIVO_VISTOS = "vistos_kwara.json"

LANCE_MINIMO = 30.0
LANCE_MAXIMO = 8500.0

PALAVRAS_CHAVE = [
    "informatica",
    "notebook",
    "mini pc",
    "mini cpu",
    "desktop",
    "monitor gamer",
    "placa de video",
    "drone",
    "dji",
    "fimi",
    "camera",
    "gopro",
    "sony",
    "canon",
    "games",
    "console",
    "xbox",
    "playstation",
    "ps5",
    "ps4",
    "nintendo",
    "switch",
    "controle",
    "dualsense"
]

PALAVRAS_BLOQUEIO = [
    "caixa vazia", "cabo avulso", "capinha", "película", "pelicula",
    "suporte parede", "adesivo", "skin", "cadeira", "mesa ", "armário",
    "armario", "fogão", "fogao", "geladeira", "roupa", "calçado", "calcado",
    "alimentos", "limpeza", "fralda"
]

def carregar_vistos():
    if os.path.exists(ARQUIVO_VISTOS):
        try:
            with open(ARQUIVO_VISTOS, "r", encoding="utf-8") as f:
                conteudo = f.read().strip()
                return set(json.loads(conteudo)) if conteudo else set()
        except Exception:
            return set()
    return set()

def salvar_vistos(vistos):
    vistos_lista = list(vistos)[-5000:]
    with open(ARQUIVO_VISTOS, "w", encoding="utf-8") as f:
        json.dump(vistos_lista, f, indent=2)

def ler_via_jina(url, timeout=25):
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", timeout=timeout)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"Erro ao ler {url}: {e}")
    return ""

def extrair_valor_lance(texto):
    padroes_prioritarios = [
        r'(?:Valor\s+atual|Lance\s+atual|Valor\s+inicial|Lance\s+a\s+partir\s+de|A\s+partir\s+de)\s*:?\s*R\$\s*([\d\.]+,\d{2})',
        r'R\$\s*([\d\.]+,\d{2})'
    ]
    for padrao in padroes_prioritarios:
        matches = re.findall(padrao, texto, flags=re.IGNORECASE)
        for m in matches:
            try:
                val = float(m.replace(".", "").replace(",", "."))
                if val > 0:
                    return val
            except ValueError:
                pass
    return 0.0

def extrair_tempo_restante(texto):
    m_tempo = re.search(
        r'Tempo\s+restante\s*:?\s*([0-9]+\s*[dMhms][0-9dMhms\s:]+)',
        texto,
        flags=re.IGNORECASE
    )
    if m_tempo:
        tempo = " ".join(m_tempo.group(1).split())[:45]
        return tempo

    m_enc = re.search(
        r'Encerramento\s*:?\s*([^\n]{5,45})',
        texto,
        flags=re.IGNORECASE
    )
    if m_enc:
        return "Encerra: " + " ".join(m_enc.group(1).split())[:45]

    m_enc2 = re.search(r'Encerra\s+(\d{2}/\d{2}/\d{2,4}\s*-\s*\d{2}h\d{0,2})', texto, flags=re.IGNORECASE)
    if m_enc2:
        return "Encerra: " + m_enc2.group(1)

    return "Verificar no link"

def extrair_localidade_sp(texto):
    m_local = re.search(r'Local\s+de\s+retirada\s*:?\s*([^\n]+)', texto, flags=re.IGNORECASE)
    if m_local:
        local = " ".join(m_local.group(1).split()).strip()
        if re.search(r'(?:/|\s-\s|\b)SP\b|São Paulo|Sao Paulo|Embu das Artes|Taboão da Serra|Taboao da Serra|São Bernardo|Santo André|Guarulhos|Barueri|Osasco|Jundiaí|Campinas', local, flags=re.IGNORECASE):
            return True, local[:90]
        return False, local[:90]

    # Caso o texto mencione retirada em SP mesmo sem o rótulo exato
    m_cidade_sp = re.search(r'([A-Za-zÀ-ÿ\s-]+/SP)\b', texto)
    if m_cidade_sp:
        return True, m_cidade_sp.group(1).strip()[:90]

    return False, "Fora de SP / Não informado"

def coletar_links_lotes_kwara():
    links_encontrados = set()

    urls_busca = ["https://www.kwara.com.br/"]
    for kw in PALAVRAS_CHAVE:
        q = urllib.parse.quote(kw)
        urls_busca.append(f"https://www.kwara.com.br/bens?search={q}")
        urls_busca.append(f"https://www.kwara.com.br/busca?q={q}")

    # Remove duplicadas mantendo a ordem
    urls_unicas = list(dict.fromkeys(urls_busca))

    for url in urls_unicas:
        print(f"[Kwara Busca] Lendo: {url}")
        texto = ler_via_jina(url, timeout=20)
        if not texto:
            continue

        matches = re.findall(r'https://www\.kwara\.com\.br/bens/[a-zA-Z0-9_-]+', texto)
        novos = 0
        for link in matches:
            if link not in links_encontrados:
                links_encontrados.add(link)
                novos += 1
        print(f"  -> Lotes encontrados nesta página: {novos} (Total acumulado: {len(links_encontrados)})")
        time.sleep(0.5)

    return list(links_encontrados)

def inspecionar_lote_kwara(link):
    texto = ler_via_jina(link, timeout=20)
    if not texto:
        return None

    texto_lower = texto.lower()
    if "lote encerrado" in texto_lower or "esse item já foi vendido" in texto_lower or "item já foi vendido" in texto_lower:
        return None

    # Extrai título principal (primeira linha com # ou título antes de Local de retirada)
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    titulo = ""
    for l in linhas:
        if l.startswith("# ") and "kwara" not in l.lower():
            titulo = l.lstrip("# ").strip()
            break
    if not titulo:
        slug = link.split("/bens/")[-1]
        titulo = re.sub(r'-\d+$', '', slug).replace("-", " ").title()

    if any(b in titulo.lower() for b in PALAVRAS_BLOQUEIO):
        return None

    eh_sp, localidade = extrair_localidade_sp(texto)
    if not eh_sp:
        return None

    lance_atual = extrair_valor_lance(texto)
    if not (LANCE_MINIMO <= lance_atual <= LANCE_MAXIMO):
        return None

    tempo_restante = extrair_tempo_restante(texto)

    # Verifica se é exclusivo PJ
    exclusivo_pj = "Exclusivo PJ (CNPJ)" if "exclusivo para pj" in texto_lower else "PF e PJ"

    # Pega um resumo da descrição/estado do lote
    m_sobre = re.search(r'(?:Sobre este item|Condição de Venda|Itens Incluídos|Conteúdo do Lote)\s*:?\s*([^\n]{10,250})', texto, flags=re.IGNORECASE)
    detalhe = " ".join(m_sobre.group(1).split()) if m_sobre else ""

    return {
        "titulo": titulo[:180],
        "lance": lance_atual,
        "tempo": tempo_restante,
        "local": localidade,
        "publico": exclusivo_pj,
        "detalhe": detalhe[:200],
        "link": link
    }

def filtrar_com_ia(candidatos):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not candidatos:
        return [], False

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=35000)
    )

    modelos_disponiveis = []
    try:
        for m in client.models.list():
            nome = m.name.replace("models/", "")
            if "flash" in nome and "image" not in nome and "audio" not in nome and "tts" not in nome:
                modelos_disponiveis.append(nome)
    except Exception:
        pass

    if not modelos_disponiveis:
        modelos_disponiveis = ["gemini-3.8-flash"]

    lista_texto = ""
    for i, item in enumerate(candidatos):
        lista_texto += (
            f"ID {i} | {item['titulo']} | Lance Atual: R$ {item['lance']:.2f} | "
            f"Local: {item['local']} | Tempo: {item['tempo']} | Público: {item['publico']} | "
            f"Info: {item['detalhe']}\n"
        )

    prompt = f"""
Você é um especialista em leilões de ativos e revenda de eletrônicos, informática, drones, câmeras e games no Brasil (2026), avaliando lotes da plataforma Kwara em São Paulo.
Lembre-se que em leilões há comissão/taxa (~5% a 10%) e os itens muitas vezes são de logística reversa ou usados sem garantia.

Analise os lotes abaixo e APROVE APENAS oportunidades reais nas áreas de:
- Informática (Notebooks recentes i5/i7/Ryzen/MacBook, Mini PCs, Monitores Gamers, Placas de Vídeo, Hardware de valor)
- Drones (DJI, Fimi, etc.)
- Câmeras (Sony, Canon, GoPro, Insta360, DJI Osmo, lentes)
- Games (PlayStation 5, PS4, Xbox Series S/X, Xbox One, Nintendo Switch, Steam Deck, controles DualSense/Xbox, volantes)

REJEITE:
- Lances atuais já próximos ao preço de usado na OLX (onde somando taxa do leilão não sobra margem).
- Velharias sem liquidez (impressoras comuns, estabilizadores, cabos soltos, notebooks muito antigos).
- Lotes que não pertençam às categorias acima.

Lotes de SP encontrados na Kwara:
{lista_texto}

Responda APENAS com um array JSON válido (se nenhum valer a pena, retorne []):
[
  {{
    "id": 0,
    "motivo": "Valor médio usado na OLX vs Lance atual | Até quanto vale dar lance (teto sugerido) e observação sobre o lote"
  }}
]
"""
    for modelo in modelos_disponiveis[:4]:
        try:
            print(f"A analisar {len(candidatos)} lotes da Kwara com IA ({modelo})...")
            res = client.models.generate_content(
                model=modelo,
                contents=prompt,
            )
            texto_limpo = res.text.strip().removeprefix("```json").removesuffix("```").strip()
            aprovados = json.loads(texto_limpo)

            finais = []
            for ap in aprovados:
                idx = ap.get("id")
                if isinstance(idx, int) and 0 <= idx < len(candidatos):
                    item = candidatos[idx]
                    item["motivo"] = ap.get("motivo", "Oportunidade de leilão identificada")
                    finais.append(item)
            return finais, True
        except Exception as e:
            print(f"Falha em {modelo}: {e}")
            time.sleep(3)

    return [], False

def enviar_telegram(achados):
    print(f"A enviar {len(achados)} lotes da Kwara para o Telegram...")
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url_texto = f"https://api.telegram.org/bot{token}/sendMessage"

    for item in achados:
        titulo_esc = html.escape(item["titulo"])
        local_esc = html.escape(item["local"])
        tempo_esc = html.escape(item["tempo"])
        publico_esc = html.escape(item["publico"])
        motivo_esc = html.escape(item["motivo"])
        link_esc = html.escape(item["link"])
        lance_fmt = f"R$ {item['lance']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        mensagem = (
            f"🔨 <b>LEILÃO KWARA (SP) - OPORTUNIDADE</b>\n\n"
            f"📦 <b>Lote:</b> {titulo_esc}\n"
            f"💰 <b>Lance Atual:</b> {lance_fmt}\n"
            f"⏳ <b>Tempo / Encerramento:</b> {tempo_esc}\n"
            f"📍 <b>Localidade:</b> {local_esc}\n"
            f"👤 <b>Participação:</b> {publico_esc}\n\n"
            f"💡 <b>Análise IA:</b>\n{motivo_esc}\n\n"
            f"🔗 {link_esc}"
        )

        for _ in range(3):
            try:
                resp = requests.post(
                    url_texto,
                    json={
                        "chat_id": chat_id,
                        "text": mensagem,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False
                    },
                    timeout=15
                )
                if resp.status_code == 200:
                    break
            except Exception:
                time.sleep(3)
        time.sleep(2)

    print("Envio concluído!")

if __name__ == "__main__":
    vistos = carregar_vistos()
    todos_links = coletar_links_lotes_kwara()

    links_novos = [l for l in todos_links if l not in vistos]
    print(f"Total de links inéditos para inspecionar: {len(links_novos)}")

    candidatos_sp = []
    # Inspeciona até 60 lotes inéditos por execução para não estourar tempo
    for link in links_novos[:60]:
        dados_lote = inspecionar_lote_kwara(link)
        vistos.add(link)
        if dados_lote:
            print(f"  [SP OK] {dados_lote['titulo'][:50]} | {dados_lote['lance']} | {dados_lote['local']} | {dados_lote['tempo']}")
            candidatos_sp.append(dados_lote)
        time.sleep(0.4)

    print(f"Lotes ativos em SP dentro das categorias: {len(candidatos_sp)}")

    oportunidades = []
    for i in range(0, len(candidatos_sp), 20):
        lote = candidatos_sp[i:i+20]
        aprovados, sucesso = filtrar_com_ia(lote)
        if sucesso:
            oportunidades.extend(aprovados)

    print(f"Oportunidades aprovadas pela IA: {len(oportunidades)}")
    if oportunidades:
        enviar_telegram(oportunidades)

    salvar_vistos(vistos)
    print("Processo Kwara finalizado!")
