#!/usr/bin/env python3
"""Gera o payload BR Code (PIX estatico) e o QR Code correspondente."""
import unicodedata

CHAVE  = "kaueramone@live.com"
NOME   = "Kaue Da Costa Pacheco"
CIDADE = "Florianopolis"

def ascii_upper(s, limite):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.upper()[:limite]

def tlv(tag, valor):
    return f"{tag}{len(valor):02d}{valor}"

def crc16(payload):
    crc = 0xFFFF
    for ch in payload.encode():
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"

nome   = ascii_upper(NOME, 25)
cidade = ascii_upper(CIDADE, 15)

mai = tlv("00", "br.gov.bcb.pix") + tlv("01", CHAVE)

payload = (
    tlv("00", "01")            # formato
    + tlv("26", mai)           # conta do recebedor
    + tlv("52", "0000")        # MCC
    + tlv("53", "986")         # moeda BRL
    + tlv("58", "BR")          # pais
    + tlv("59", nome)          # recebedor
    + tlv("60", cidade)        # cidade
    + tlv("62", tlv("05", "***"))   # txid livre
)
payload += "6304" + crc16(payload + "6304")

print("nome   :", nome, f"({len(nome)} chars)")
print("cidade :", cidade, f"({len(cidade)} chars)")
print("tamanho:", len(payload))
print()
print(payload)

with open("/root/doispapo/assets/pix/payload.txt", "w") as f:
    f.write(payload)
