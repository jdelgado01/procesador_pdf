import streamlit as st
import pandas as pd
import pdfplumber
import io
from pathlib import Path
import sys
import importlib

# Configuración de la página
st.set_page_config(
    page_title="Extractor de Estados de Cuenta y Préstamos",
    page_icon="📊",
    layout="wide"
)

# Estilo CSS personalizado
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stProgress > div > div > div > div {
        background-color: #1E88E5;
    }
    </style>
""", unsafe_allow_html=True)

# Diccionario de entidades bancarias
ENTIDADES = {
    "BCP": ["Prestamo", "Estado de cuenta"],
    "INTERBANK": ["Prestamo", "Estado de cuenta"],
    "PICHINCHA": ["Prestamo", "Estado de cuenta"],
    "SCOTIABANK": ["Prestamo", "Estado de cuenta"],
    "BBVA": ["Prestamo", "Estado de cuenta"],
    "RIPLEY": ["Estado de cuenta"],
    "FALABELLA": ["Estado de cuenta"],
    "DINNERS": ["Estado de cuenta"],
    "COMPARTAMOS": ["Prestamo"],
    "GNB": ["Prestamo"],
    "ALFIN BANCO": ["Prestamo"],
    "MIBANCO": ["Prestamo"]
}

def main():
    st.title("📊 Extractor de Estados de Cuenta y Préstamos")
    
    # Sidebar para controles
    with st.sidebar:
        st.header("Configuración")
        
        # Selector de entidad
        entidad = st.selectbox(
            "Seleccione la entidad bancaria",
            options=list(ENTIDADES.keys())
        )
        
        # Selector de tipo de documento
        tipo_doc = st.radio(
            "Seleccione el tipo de documento",
            options=ENTIDADES[entidad]
        )
        
        # Información adicional
        st.info("💡 Esta aplicación procesa archivos PDF de estados de cuenta y préstamos bancarios.")
        
    # Área principal
    uploaded_file = st.file_uploader(
        "Seleccione el archivo PDF a procesar",
        type="pdf",
        help="Máximo 300MB"
    )
    
    if uploaded_file is not None:
        # Validar tamaño del archivo
        file_size = uploaded_file.size / (1024 * 1024)  # Convertir a MB
        if file_size > 300:
            st.error("⚠️ El archivo excede el límite de 300MB")
            return
        
        try:
            # Mostrar barra de progreso
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Construir el nombre del módulo a importar
            module_name = f"procesadores.{entidad.lower().replace(' ', '_')}_{tipo_doc.lower().replace(' ', '_')}"
            
            try:
                # Importar el módulo correspondiente
                processor = importlib.import_module(module_name)
                
                # Procesar el archivo
                status_text.text("Procesando el archivo PDF...")
                progress_bar.progress(30)
                
                # Leer el PDF
                pdf_bytes = uploaded_file.read()
                
                # Procesar según el tipo de documento
                df_result = processor.procesar_documento(pdf_bytes)
                
                progress_bar.progress(70)
                status_text.text("Generando archivo Excel...")
                
                # Generar Excel en memoria
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    if isinstance(df_result, dict):
                        for sheet_name, df in df_result.items():
                            df.to_excel(writer, sheet_name=sheet_name, index=False)
                    else:
                        df_result.to_excel(writer, index=False)
                
                progress_bar.progress(100)
                status_text.text("¡Proceso completado!")
                
                # Ofrecer el archivo para descarga
                st.download_button(
                    label="📥 Descargar Excel",
                    data=output.getvalue(),
                    file_name=f"{entidad}_{tipo_doc}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            except ImportError:
                st.error(f"⚠️ Procesador no encontrado para {entidad} - {tipo_doc}")
                
        except Exception as e:
            st.error(f"⚠️ Error al procesar el archivo: {str(e)}")
            
if __name__ == "__main__":
    main()
