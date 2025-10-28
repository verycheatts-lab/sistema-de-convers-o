# app.py

import os
import time
import uuid
import threading
import json
from flask import Flask, request, render_template, send_from_directory, jsonify, Response
import yt_dlp

# yt-dlp precisa do FFmpeg para converter para mp3
# A opção 'outtmpl' define o nome do arquivo de saída
# 'format': 'bestaudio/best' -> baixa a melhor qualidade de áudio
# 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] -> extrai o áudio e converte para mp3
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(title)s.%(ext)s', # Salva com o título do vídeo
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'noplaylist': True, # Evita baixar playlists inteiras
    # 'ffmpeg_location' não é mais necessário, pois o FFmpeg estará no PATH do container.
}

# Dicionário para armazenar o progresso dos downloads (não é seguro para produção com múltiplos workers)
download_progress = {}


app = Flask(__name__)
DOWNLOAD_FOLDER = 'downloads'

# Garante que a pasta de downloads exista
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    """ Rota principal que renderiza a página HTML. """
    return render_template('index.html')

def download_task(video_url, task_id):
    """ Função que executa o download em uma thread separada. """

    class CancelledError(Exception):
        """ Exceção customizada para o cancelamento. """
        pass

    def progress_hook(d):
        """ Hook para capturar o progresso do yt-dlp. """
        if download_progress.get(task_id, {}).get('status') == 'cancelling':
            raise CancelledError("Download cancelado pelo usuário.")

        if d['status'] == 'downloading':
            # Extrai a porcentagem e remove espaços e a cor (se houver)
            percent_str = d.get('_percent_str', '0.0%').strip().replace('%', '')
            try:
                # Converte para float e depois para inteiro
                progress = int(float(percent_str))
                download_progress[task_id]['progress'] = progress
            except ValueError:
                pass # Ignora se não conseguir converter
        
        if d['status'] == 'finished':
            # Prepara o nome do arquivo final
            # yt-dlp pode salvar com .webm e depois converter, então pegamos o nome do arquivo final
            output_filename = d['filename']
            base_filename = os.path.basename(output_filename).replace(os.path.splitext(output_filename)[1], '.mp3')
            download_progress[task_id]['progress'] = 100
            download_progress[task_id]['status'] = 'finished'
            download_progress[task_id]['filename'] = base_filename

    ydl_opts_task = YDL_OPTIONS.copy()
    ydl_opts_task['progress_hooks'] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts_task) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            download_progress[task_id]['title'] = info_dict.get('title', 'video')
    except CancelledError:
        print(f"Tarefa {task_id} cancelada pelo usuário.")
        download_progress[task_id]['status'] = 'cancelled'
        # Arquivos parciais podem ficar, uma limpeza futura seria ideal
    except Exception as e:
        print(f"Erro na thread de download: {e}")
        download_progress[task_id]['status'] = 'error'
        download_progress[task_id]['error'] = str(e)

@app.route('/convert', methods=['POST'])
def convert():
    """ Inicia o processo de conversão e retorna um ID de tarefa. """
    video_url = request.json.get('url')
    if not video_url:
        return jsonify({'error': 'URL não fornecida.'}), 400

    try:
        # Extrai informações rapidamente sem fazer o download
        with yt_dlp.YoutubeDL({'noplaylist': True, 'quiet': True}) as ydl:
            info_dict = ydl.extract_info(video_url, download=False)
            title = info_dict.get('title', 'Título desconhecido')
            thumbnail = info_dict.get('thumbnail', None)

        task_id = str(uuid.uuid4())
        download_progress[task_id] = {'status': 'downloading', 'progress': 0, 'title': title}

        # Inicia o download em uma thread para não bloquear a resposta
        thread = threading.Thread(target=download_task, args=(video_url, task_id))
        thread.start()

        return jsonify({'task_id': task_id, 'title': title, 'thumbnail': thumbnail})

    except Exception as e:
        print(f"Erro ao extrair informações do vídeo: {e}")
        return jsonify({'error': 'Não foi possível obter informações do vídeo. Verifique a URL.'}), 500

@app.route('/cancel/<task_id>', methods=['POST'])
def cancel_download(task_id):
    """ Sinaliza uma tarefa de download para ser cancelada. """
    if task_id in download_progress:
        # Apenas muda o status, o progress_hook na thread fará o resto
        download_progress[task_id]['status'] = 'cancelling'
        return jsonify({'message': 'Sinal de cancelamento enviado.'})
    return jsonify({'error': 'Tarefa não encontrada.'}), 404

@app.route('/progress/<task_id>')
def progress(task_id):
    """ Rota que envia o progresso do download via Server-Sent Events (SSE). """
    def generate():
        while download_progress.get(task_id) and download_progress[task_id].get('status') in ['downloading', 'cancelling']:
            progress_val = download_progress[task_id].get('progress', 0)
            yield f"data: {progress_val}\n\n"
            time.sleep(0.5)
        # Envia o resultado final
        yield f"data: {json.dumps(download_progress.get(task_id, {}))}\n\n" # Esta linha precisa do módulo 'json'
    return Response(generate(), mimetype='text/event-stream')

@app.route('/download/<filename>')
def download_file(filename):
    """ Rota para servir o arquivo MP3 para download. """
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)
