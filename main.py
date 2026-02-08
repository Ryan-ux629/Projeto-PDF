from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
import img2pdf
from pdf2image import convert_from_bytes
import io
import os

app = FastAPI()

# Rota para mostrar a página (Frontend)
@app.get("/", response_class=HTMLResponse)
async def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()

# ROTA 1: Transforma FOTO em PDF
@app.post("/converter-para-pdf")
async def converter_para_pdf(arquivo: UploadFile = File(...)):
    # Lê a imagem que você enviou
    conteudo_imagem = await arquivo.read()
    
    # Converte para PDF na memória (sem salvar no disco para ser rápido)
    pdf_bytes = img2pdf.convert(conteudo_imagem)
    
    # Cria um nome para o arquivo
    nome_saida = "convertido.pdf"
    
    # Salva temporariamente para enviar de volta
    with open(nome_saida, "wb") as f:
        f.write(pdf_bytes)
        
    return FileResponse(nome_saida, media_type='application/pdf', filename=nome_saida)

# ROTA 2: Transforma PDF em FOTO (Pega a 1ª página)
@app.post("/converter-para-imagem")
async def converter_para_imagem(arquivo: UploadFile = File(...)):
    conteudo_pdf = await arquivo.read()
    
    # Converte a primeira página do PDF em imagem
    imagens = convert_from_bytes(conteudo_pdf)
    primeira_pagina = imagens[0]
    
    nome_saida = "pagina_1.jpg"
    primeira_pagina.save(nome_saida, "JPEG")
    
    return FileResponse(nome_saida, media_type='image/jpeg', filename=nome_saida)
