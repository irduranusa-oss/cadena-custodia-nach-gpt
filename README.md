# 🦷 NACH-GPT — Cadena de Custodia Automática

Sistema de gestión y seguimiento de casos para laboratorio dental.

Permite:
- Crear órdenes de trabajo con QR únicos por paciente.
- Escanear los QR de los empleados para registrar cada etapa del flujo (recepción, nesteado, fresado, sinterizado, porcelana, cementado, calidad y envío).
- Consultar el estado de cada caso desde cualquier dispositivo autorizado.

## 🚀 Tecnologías
- Python (Flask)
- HTML + CSS + JavaScript
- SQLite o JSON para almacenamiento local
- Generación de códigos QR
- Enlace seguro para acceso remoto (Render o Ngrok)

## ⚙️ Instalación local
1. Clonar este repositorio:
   ```bash
   git clone https://github.com/tu_usuario/cadena-custodia-nach-gpt.git
   cd cadena-custodia-nach-gpt
   ```
2. Crear un archivo `.env` con tus variables de entorno (usa `.env.example` como plantilla).
3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Ejecutar:
   ```bash
   python app.py
   ```
5. Abrir en el navegador:
   ```
   http://127.0.0.1:5000
   ```

## 👨‍🔬 Desarrollado por
Laboratorio Dental Nach — Automatización con IA.
