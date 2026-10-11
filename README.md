# PDF Bookmark Maker

Web app para subir un PDF y devolver una copia con el índice convertido en bookmarks / esquema navegable.

## Cómo funciona

1. El usuario sube un PDF.
2. El backend busca páginas tempranas con `Índice`, `Contenido`, `Contents`, `Table of Contents`, etc. y entradas que terminen en número de página.
3. Las entradas se parsean y se intenta inferir la jerarquía mediante numeración (`1`, `1.1`, `1.1.1`) e indentación.
4. Se calcula la correspondencia entre números de página impresos y páginas físicas del PDF, buscando los títulos en el propio documento.
5. PyMuPDF escribe el árbol de bookmarks en el PDF de salida.

## Ejecutar en local

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre http://127.0.0.1:8000

## Docker

```bash
docker build -t pdf-bookmark-maker .
docker run --rm -p 8000:8000 pdf-bookmark-maker
```

## Limitaciones actuales

El detector es heurístico y funciona mejor con PDFs que contienen texto real en la página del índice. Los PDFs escaneados como imágenes necesitan una capa OCR adicional. Algunos índices muy gráficos, con varias columnas o numeración no convencional, pueden necesitar ajustes de parsing.

Para convertirlo en una aplicación pública conviene añadir límites de concurrencia, limpieza de temporales, logging, antivirus/validación adicional y, si el volumen es alto, una cola de trabajos.
