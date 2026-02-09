from fastapi import FastAPI, UploadFile, File, Request, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import img2pdf
from pdf2image import convert_from_bytes
import os
import tempfile
import logging
import re
from typing import Optional

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuração de templates
templates = Jinja2Templates(directory="templates")

def cleanup_file(path: str):
    """Remove o arquivo temporário após o uso."""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Arquivo removido: {path}")
    except Exception as e:
        logger.error(f"Erro ao remover arquivo {path}: {e}")

def sanitize_filename(filename: Optional[str], default: str, extension: str) -> str:
    """Sanitiza o nome do arquivo e garante a extensão correta."""
    if not filename or not filename.strip():
        return default

    # Remove caracteres inválidos para nomes de arquivos
    # Mantém apenas letras, números, sublinhados, hífens e pontos
    sanitized = re.sub(r'[^\w\-. ]', '', filename.strip())

    if not sanitized:
        return default

    # Garante que a extensão está correta
    if not sanitized.lower().endswith(extension):
        sanitized += extension

    return sanitized

# Rota para mostrar a página (Frontend)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ROTA 1: Transforma FOTO em PDF
@app.post("/converter-para-pdf")
async def converter_para_pdf(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    nome_arquivo: Optional[str] = Form(None)
):
    # Validação simples do tipo de arquivo
    if not arquivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="O arquivo deve ser uma imagem válida.")

    try:
        # Lê a imagem
        conteudo_imagem = await arquivo.read()
        if not conteudo_imagem:
            raise HTTPException(status_code=400, detail="O arquivo está vazio.")

        # Converte para PDF bytes
        pdf_bytes = img2pdf.convert(conteudo_imagem)

        # Cria um arquivo temporário
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name

        # Agenda a remoção do arquivo após o envio da resposta
        background_tasks.add_task(cleanup_file, tmp_path)

        # Define o nome de saída
        filename_output = sanitize_filename(nome_arquivo, "convertido.pdf", ".pdf")

        return FileResponse(
            tmp_path,
            media_type='application/pdf',
            filename=filename_output
        )

    except img2pdf.ImageOpenError:
        raise HTTPException(status_code=400, detail="Imagem inválida ou corrompida.")
    except Exception as e:
        logger.error(f"Erro na conversão para PDF: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar a imagem.")

# ROTA 2: Transforma PDF em FOTO (Pega a 1ª página)
@app.post("/converter-para-imagem")
async def converter_para_imagem(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    nome_arquivo: Optional[str] = Form(None)
):
    # Validação simples
    if arquivo.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="O arquivo deve ser um PDF válido.")
    
    try:
        conteudo_pdf = await arquivo.read()
        if not conteudo_pdf:
             raise HTTPException(status_code=400, detail="O arquivo está vazio.")

        # Converte a primeira página do PDF em imagem
        imagens = convert_from_bytes(conteudo_pdf)
        if not imagens:
            raise HTTPException(status_code=400, detail="Não foi possível extrair imagens do PDF.")

        primeira_pagina = imagens[0]

        # Cria arquivo temporário
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            primeira_pagina.save(tmp_file.name, "JPEG")
            tmp_path = tmp_file.name

        # Agenda limpeza
        background_tasks.add_task(cleanup_file, tmp_path)

        # Define o nome de saída
        filename_output = sanitize_filename(nome_arquivo, "pagina_1.jpg", ".jpg")

        return FileResponse(
            tmp_path,
            media_type='image/jpeg',
            filename=filename_output
        )
    
    except Exception as e:
        logger.error(f"Erro na conversão para Imagem: {e}")
        # Retorna erro genérico, mas loga o detalhe
        raise HTTPException(status_code=500, detail="Erro interno ao processar o PDF. Verifique se o arquivo é válido.")
