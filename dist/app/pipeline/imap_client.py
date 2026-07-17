"""
Cliente IMAP para caixas de e-mail cPanel (ex: mail.ddm.adv.br).
Substitui a leitura via Microsoft Graph para contas que NÃO estão no Microsoft 365.

Config via .env:
    IMAP_HOST=mail.ddm.adv.br
    IMAP_PORT=993
    IMAP_USER=gisele.oliveira@ddm.adv.br
    IMAP_PASSWORD=...          (senha da conta de e-mail — NUNCA commitar)

Limitação: IMAP exige credencial por caixa. Cobre apenas as contas configuradas.
"""

import email
import imaplib
import os
import re
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime, getaddresses

from dotenv import load_dotenv

load_dotenv()


def _decode(raw) -> str:
    """Decodifica header MIME (=?UTF-8?Q?...?=) para texto legível."""
    if not raw:
        return ""
    partes = decode_header(raw)
    out = []
    for texto, enc in partes:
        if isinstance(texto, bytes):
            out.append(texto.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(texto)
    return "".join(out).strip()


def _html_para_texto(html: str) -> str:
    """Remove tags/estilos de HTML e retorna texto aproximado."""
    html = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html)
    texto = re.sub(r"(?s)<[^>]+>", " ", html)
    texto = re.sub(r"&nbsp;", " ", texto)
    texto = re.sub(r"&amp;", "&", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _decode_part(part) -> str:
    carga = part.get_payload(decode=True)
    if carga is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return carga.decode(charset, errors="ignore")


def _extrair_corpo(msg: email.message.Message, limite: int = 8000) -> str:
    """Retorna texto do corpo: prefere text/plain; se só houver HTML, converte."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and not plain:
                plain = _decode_part(part)
            elif ctype == "text/html" and not html:
                html = _decode_part(part)
    else:
        if msg.get_content_type() == "text/html":
            html = _decode_part(msg)
        else:
            plain = _decode_part(msg)

    texto = plain.strip() or _html_para_texto(html)
    return texto.strip()[:limite]


def _conectar() -> imaplib.IMAP4_SSL:
    host = os.getenv("IMAP_HOST", "")
    port = int(os.getenv("IMAP_PORT", "993"))
    user = os.getenv("IMAP_USER", "")
    pw = os.getenv("IMAP_PASSWORD", "")
    if not (host and user and pw):
        raise RuntimeError("IMAP_HOST / IMAP_USER / IMAP_PASSWORD não configurados no .env")
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pw)
    return M


def get_emails_imap(since: datetime, pasta: str = "INBOX", limite: int = 100) -> list[dict]:
    """
    Busca e-mails recebidos desde `since` (datetime). Retorna lista de dicts no
    mesmo formato consumido pela task de processamento.
    """
    M = _conectar()
    try:
        M.select(pasta)
        criterio = since.strftime("%d-%b-%Y")  # IMAP: SINCE 06-Jul-2026
        typ, data = M.search(None, "SINCE", criterio)
        if typ != "OK":
            return []

        ids = data[0].split()
        ids = ids[-limite:]  # mais recentes
        resultados = []

        for i in ids:
            typ, msg_data = M.fetch(i, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            de_nome, de_email = _parse_remetente(msg.get("From", ""))
            destinatarios = [
                {"nome": n, "email": e.lower()}
                for n, e in getaddresses([msg.get("To", "")])
                if e
            ]

            data_iso = None
            if msg.get("Date"):
                try:
                    data_iso = parsedate_to_datetime(msg["Date"]).isoformat()
                except Exception:
                    data_iso = None

            resultados.append({
                "message_id": (msg.get("Message-ID") or "").strip() or f"imap-{i.decode()}",
                "de_nome": de_nome,
                "de_email": de_email.lower(),
                "para": destinatarios,
                "assunto": _decode(msg.get("Subject", "")),
                "corpo": _extrair_corpo(msg),
                "data": data_iso,
                "thread_id": (msg.get("References") or msg.get("In-Reply-To") or "").strip(),
            })
        return resultados
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _parse_remetente(raw: str) -> tuple[str, str]:
    enderecos = getaddresses([raw])
    if enderecos:
        nome, addr = enderecos[0]
        return _decode(nome), addr
    return "", ""
