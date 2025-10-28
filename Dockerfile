# 1. Imagem base: Começamos com uma imagem oficial do Python.
FROM python:3.10-slim

# 2. Definir o diretório de trabalho dentro do container
WORKDIR /app

# 3. Instalar o FFmpeg (dependência do sistema)
# Atualizamos a lista de pacotes e instalamos o ffmpeg sem prompts interativos
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    # Limpamos o cache para manter a imagem pequena
    rm -rf /var/lib/apt/lists/*

# 4. Copiar o arquivo de dependências e instalá-las
# Copiamos primeiro para aproveitar o cache do Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cookies.txt .

# 5. Copiar o resto do código da aplicação para o container
COPY . .

# 6. Expor a porta que a aplicação usará (Gunicorn usará a porta 8000 por padrão)
EXPOSE 8000

# 7. Comando para rodar a aplicação com Gunicorn quando o container iniciar
# O 'app:app' significa: no arquivo 'app.py', encontre a instância Flask chamada 'app'.
CMD ["gunicorn", "app:app"]
