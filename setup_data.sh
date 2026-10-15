#!/usr/bin/env bash
mkdir -p data
cd data
if [ ! -d "train-ticket" ]; then
    echo "Клонируем train-ticket..."
    git clone https://github.com/FudanSELab/train-ticket.git
    cd train-ticket
    echo "Датасет успешно скачан"
fi