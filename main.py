from fastapi import FastAPI, UploadFile, File, Request, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import img2pdf
from pdf2image import convert_from_bytes
import os
import tempfile
import logging
import re
import magic
from typing import Optional, List

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especifique os domínios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Constantes de Segurança
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif"]
ALLOWED_PDF_TYPES = ["application/pdf"]

# Middleware de Segurança para Headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdnjs.cloudflare.com"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)

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
    sanitized = re.sub(r'[^\w\-. ]', '', filename.strip())

    if not sanitized:
        return default

    # Garante que a extensão está correta
    if not sanitized.lower().endswith(extension):
        sanitized += extension

    return sanitized

async def save_upload_file_tmp(upload_file: UploadFile) -> str:
    """Salva o arquivo enviado em um local temporário verificando o tamanho."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            size = 0
            while content := await upload_file.read(1024 * 1024):  # Lê em chunks de 1MB
                size += len(content)
                if size > MAX_FILE_SIZE:
                    tmp_file.close()
                    os.remove(tmp_file.name)
                    raise HTTPException(status_code=413, detail="O arquivo excede o tamanho máximo permitido de 10MB.")
                tmp_file.write(content)
            return tmp_file.name
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao salvar arquivo temporário: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar o upload.")

def validate_file_type(file_path: str, allowed_types: list[str]):
    """Valida o tipo do arquivo usando python-magic."""
    try:
        mime_type = magic.from_file(file_path, mime=True)
        if mime_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Tipo de arquivo inválido: {mime_type}. Permitidos: {', '.join(allowed_types)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro na validação do tipo de arquivo: {e}")
        raise HTTPException(status_code=400, detail="Não foi possível validar o tipo do arquivo.")

# Rota para mostrar a página (Frontend)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ROTA 1: Transforma FOTO em PDF
@app.post("/converter-para-pdf")
async def converter_para_pdf(
    background_tasks: BackgroundTasks,
    arquivo: List[UploadFile] = File(...),
    nome_arquivo: Optional[str] = Form(None)
):
    tmp_input_paths = []
    tmp_output_path = None

    try:
        if not arquivo:
             raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

        # Processa cada imagem
        for file in arquivo:
            # Validação simples
            if not file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail=f"O arquivo {file.filename} deve ser uma imagem válida.")

            # Salva temporariamente
            tmp_path = await save_upload_file_tmp(file)
            tmp_input_paths.append(tmp_path)

            # Agenda limpeza (caso ocorra erro antes do final)
            background_tasks.add_task(cleanup_file, tmp_path)

            # Valida tipo
            validate_file_type(tmp_path, ALLOWED_IMAGE_TYPES)

        # Converte para PDF
        try:
            # img2pdf aceita lista de caminhos de arquivos
            pdf_bytes = img2pdf.convert(tmp_input_paths)
        except Exception as e:
            logger.warning(f"img2pdf falhou: {e}")
            raise HTTPException(status_code=400, detail="Erro ao converter imagens. Verifique se são válidas.")

        # Cria arquivo de saída
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_output_file:
            tmp_output_file.write(pdf_bytes)
            tmp_output_path = tmp_output_file.name

        # Agenda a remoção do arquivo de saída
        background_tasks.add_task(cleanup_file, tmp_output_path)

        # Define o nome de saída
        filename_output = sanitize_filename(nome_arquivo, "convertido.pdf", ".pdf")

        return FileResponse(
            tmp_output_path,
            media_type='application/pdf',
            filename=filename_output
        )

    except HTTPException:
        # Em caso de erro HTTP, limpa os arquivos criados até agora
        for path in tmp_input_paths:
            cleanup_file(path)
        if tmp_output_path: cleanup_file(tmp_output_path)
        raise
    except Exception as e:
        logger.error(f"Erro inesperado na conversão para PDF: {e}")
        for path in tmp_input_paths:
            cleanup_file(path)
        if tmp_output_path: cleanup_file(tmp_output_path)
        raise HTTPException(status_code=500, detail="Erro interno ao processar a solicitação.")

# ROTA 2: Transforma PDF em FOTO (Pega a 1ª página)
@app.post("/converter-para-imagem")
async def converter_para_imagem(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    nome_arquivo: Optional[str] = Form(None)
):
    tmp_input_path = None
    tmp_output_path = None
    
    try:
        # Salva o arquivo temporariamente verificando o tamanho
        tmp_input_path = await save_upload_file_tmp(arquivo)

        # Agenda limpeza do arquivo de entrada
        background_tasks.add_task(cleanup_file, tmp_input_path)

        # Valida o tipo do arquivo
        validate_file_type(tmp_input_path, ALLOWED_PDF_TYPES)

        # Converte a primeira página do PDF em imagem
        try:
            with open(tmp_input_path, "rb") as f:
                pdf_bytes = f.read()
            imagens = convert_from_bytes(pdf_bytes)
        except Exception as e:
             logger.warning(f"pdf2image falhou: {e}")
             raise HTTPException(status_code=400, detail="Arquivo PDF inválido ou corrompido.")

        if not imagens:
            raise HTTPException(status_code=400, detail="Não foi possível extrair imagens do PDF.")

        primeira_pagina = imagens[0]

        # Cria arquivo temporário de saída
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_output_file:
            primeira_pagina.save(tmp_output_file.name, "JPEG")
            tmp_output_path = tmp_output_file.name

        # Agenda limpeza
        background_tasks.add_task(cleanup_file, tmp_output_path)

        # Define o nome de saída
        filename_output = sanitize_filename(nome_arquivo, "pagina_1.jpg", ".jpg")

        return FileResponse(
            tmp_output_path,
            media_type='image/jpeg',
            filename=filename_output
        )
    
    except HTTPException:
        if tmp_input_path: cleanup_file(tmp_input_path)
        if tmp_output_path: cleanup_file(tmp_output_path)
        raise
    except Exception as e:
        logger.error(f"Erro inesperado na conversão para Imagem: {e}")
        if tmp_input_path: cleanup_file(tmp_input_path)
        if tmp_output_path: cleanup_file(tmp_output_path)
        raise HTTPException(status_code=500, detail="Erro interno ao processar a solicitação.")
