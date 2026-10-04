#!/usr/bin/env bash
pkill -f "uvicorn services[.]" || true
pkill -f "streamlit run ui[/]streamlit_app.py" || true
echo stopped
