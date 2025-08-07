import streamlit as st
import pandas as pd
import numpy as np
import io
import math

# --- Funciones de Lógica de Negocio (sin cambios) ---

def parse_original_name(name):
    try:
        parts = name.split('_')
        seguidor = parts[0]
        tipo_punto = parts[1]
        return seguidor, tipo_punto
    except IndexError:
        return None, None

def parse_auxiliary_name(name):
    try:
        parts = name.split('_')
        if parts[1].isdigit():
            return None, None
        seguidor = parts[0]
        tipo_auxiliar = parts[1]
        return seguidor, tipo_auxiliar
    except (IndexError, AttributeError):
        return None, None

# --- Diseño de la Interfaz de la Aplicación ---

st.set_page_config(layout="wide", page_title="Analizador GPS de Seguidores")
st.title("🛰️ Analizador de Distancias Reducidas para Seguidores")
st.write("Esta aplicación calcula la coordenada Y ajustada por fila (Este/Oeste) basándose en la pendiente real de los puntos auxiliares.")

# --- Inicialización del Estado de la Sesión ---
if 'analysis_done' not in st.session_state:
    st.session_state.analysis_done = False
    st.session_state.df_originals = None
    st.session_state.df_auxiliares = None
    st.session_state.df_final = None
    st.session_state.df_missing = None
    st.session_state.log_messages = []
    st.session_state.summary_text = ""

# --- Barra Lateral para Carga de Ficheros y Acciones ---
with st.sidebar:
    st.header("1. Carga de Ficheros")
    uploaded_originals = st.file_uploader("Cargar Originales (NOMBRE,X,Y,Z)", type=['txt', 'csv'])
    uploaded_auxiliares = st.file_uploader("Cargar Auxiliares (Nombre,X,Y,Zreal)", type=['txt', 'csv'])

    if uploaded_originals:
        try:
            df_orig = pd.read_csv(uploaded_originals, header=None, names=['NOMBRE', 'X', 'Y', 'Z'])
            parsed_data = df_orig['NOMBRE'].apply(parse_original_name)
            df_orig[['SEGUIDOR', 'TIPO_PUNTO']] = pd.DataFrame(parsed_data.tolist(), index=df_orig.index)
            st.session_state.df_originals = df_orig
            st.success("Fichero de Originales cargado.")
        except Exception as e:
            st.error(f"Error al leer el fichero de originales: {e}")

    if uploaded_auxiliares:
        try:
            df_aux = pd.read_csv(uploaded_auxiliares, header=None, names=['NOMBRE', 'X', 'Y', 'Z_REAL'])
            parsed_data = df_aux['NOMBRE'].apply(parse_auxiliary_name)
            df_aux[['SEGUIDOR', 'TIPO_PUNTO']] = pd.DataFrame(parsed_data.tolist(), index=df_aux.index)
            df_aux.dropna(subset=['SEGUIDOR'], inplace=True)
            st.session_state.df_auxiliares = df_aux
            st.success("Fichero de Auxiliares cargado.")
        except Exception as e:
            st.error(f"Error al leer el fichero de auxiliares: {e}")

    st.header("2. Ejecutar Análisis")
    if st.button("Realizar Análisis Completo", type="primary"):
        if st.session_state.df_originals is not None and st.session_state.df_auxiliares is not None:
            df_orig = st.session_state.df_originals
            df_aux = st.session_state.df_auxiliares
            
            df_final = df_orig.copy()
            df_final['Y_AJUSTADA'] = np.nan
            df_final['CODIGO'] = ""
            
            missing_aux_data, log_messages = [], []
            SET_ESTE, SET_OESTE = {'EN', 'EO', 'ES'}, {'WN', 'WO', 'WS'}
            
            summary = df_orig['TIPO_PUNTO'].value_counts().to_dict()
            hincas_count = sum(1 for item in df_orig['TIPO_PUNTO'] if item.isdigit())
            aux_summary = {k: v for k, v in summary.items() if not k.isdigit()}
            st.session_state.summary_text = f"Total Hincas: {hincas_count} | " + " | ".join([f"{k}: {v}" for k, v in aux_summary.items()])

            for seguidor_id, group in df_orig.groupby('SEGUIDOR'):
                hincas_del_seguidor = group[group['TIPO_PUNTO'].str.isdigit()].copy()
                if hincas_del_seguidor.empty: continue
                hincas_del_seguidor['HINCA_NUM'] = pd.to_numeric(hincas_del_seguidor['TIPO_PUNTO'])
                total_hincas, midpoint_hinca = len(hincas_del_seguidor), len(hincas_del_seguidor) / 2.0

                aux_points_reales = df_aux[df_aux['SEGUIDOR'] == seguidor_id]
                if aux_points_reales.empty: continue
                present_aux = set(aux_points_reales['TIPO_PUNTO'])
                
                def ajustar_fila(set_requerido, p_n_id, p_s_id, p_c_id, fila_nombre):
                    if any(aux in present_aux for aux in set_requerido):
                        missing = set_requerido - present_aux
                        if not missing:
                            log_messages.append(f"✅ {seguidor_id}: Fila {fila_nombre} completa. Analizando pendiente...")
                            p_n = aux_points_reales[aux_points_reales['TIPO_PUNTO'] == p_n_id].iloc[0]
                            p_s = aux_points_reales[aux_points_reales['TIPO_PUNTO'] == p_s_id].iloc[0]
                            p_c = aux_points_reales[aux_points_reales['TIPO_PUNTO'] == p_c_id].iloc[0]

                            delta_y_total = p_n['Y'] - p_s['Y']
                            if delta_y_total == 0:
                                log_messages.append(f"⚠️ {seguidor_id}: Distancia Y entre {p_n_id} y {p_s_id} es cero.")
                                return

                            pendiente_percent = (abs(p_n['Z_REAL'] - p_s['Z_REAL']) / abs(delta_y_total)) * 100
                            
                            if pendiente_percent > 5.0:
                                log_messages.append(f"    -> 📈 Pendiente: {pendiente_percent:.2f}% (>5%). SE AJUSTARÁ Y.")
                                # Usamos la pendiente en valor absoluto para el cálculo de Pitágoras
                                pendiente_ratio_abs = abs((p_n['Z_REAL'] - p_s['Z_REAL']) / delta_y_total)
                                
                                hincas_a_ajustar = hincas_del_seguidor[hincas_del_seguidor['HINCA_NUM'] > midpoint_hinca] if fila_nombre == 'ESTE' else hincas_del_seguidor[hincas_del_seguidor['HINCA_NUM'] <= midpoint_hinca]
                                log_messages.append(f"    -> Aplicando a hincas {fila_nombre}: {list(hincas_a_ajustar['TIPO_PUNTO'])}")
                                
                                for index, hinca in hincas_a_ajustar.iterrows():
                                    # Distancia proyectada original, determina la dirección (Norte/Sur)
                                    dist_y_proyectada = hinca['Y'] - p_c['Y']
                                    
                                    # El cateto vertical se calcula con la pendiente absoluta
                                    delta_z_teorico = abs(dist_y_proyectada) * pendiente_ratio_abs
                                    
                                    try:
                                        # La hipotenusa es la distancia proyectada en Y
                                        hipotenusa_y = abs(dist_y_proyectada)
                                        
                                        # El nuevo cateto horizontal (distancia reducida)
                                        dist_y_reducida = math.sqrt(hipotenusa_y**2 - delta_z_teorico**2)
                                        
                                        # La Y ajustada es la Y del centro + la distancia reducida en la dirección correcta
                                        y_ajustada = p_c['Y'] + (np.sign(dist_y_proyectada) * dist_y_reducida)
                                        
                                        df_final.loc[index, 'Y_AJUSTADA'] = y_ajustada
                                        df_final.loc[index, 'CODIGO'] = 'ajustado'
                                    except ValueError:
                                        log_messages.append(f"    -> ❌ Error matemático en {hinca['NOMBRE']}. Pendiente >100%. Se omite.")
                                        df_final.loc[index, 'CODIGO'] = 'error_ajuste'
                            else:
                                log_messages.append(f"    -> 📉 Pendiente: {pendiente_percent:.2f}% (<=5%). OK, no requiere ajuste.")
                        else:
                            missing_info = {'SEGUIDOR': seguidor_id, 'FALTANTES': ','.join(sorted(list(missing)))}
                            missing_aux_data.append(missing_info)
                            log_messages.append(f"❌ {seguidor_id}: Fila {fila_nombre} incompleta. Faltan: {', '.join(missing)}")
                
                ajustar_fila(SET_ESTE, 'EN', 'ES', 'EO', 'ESTE')
                ajustar_fila(SET_OESTE, 'WN', 'WS', 'WO', 'OESTE')
            
            st.session_state.analysis_done = True
            st.session_state.df_final = df_final
            st.session_state.df_missing = pd.DataFrame(missing_aux_data).drop_duplicates().reset_index(drop=True)
            st.session_state.log_messages = log_messages
            st.success("Análisis completado con éxito.")
        else:
            st.error("Por favor, carga ambos ficheros (Originales y Auxiliares) antes de analizar.")

    st.header("3. Exportar Resultados")
    
    if st.session_state.analysis_done and st.session_state.df_final is not None:
        df_completo = st.session_state.df_final.copy()
        df_export = df_completo[df_completo['CODIGO'] == 'ajustado'].copy()
        
        if not df_export.empty:
            df_export['Y_FINAL'] = df_export['Y_AJUSTADA']
            df_export_final = df_export[['NOMBRE', 'X', 'Y_FINAL', 'Z', 'CODIGO']]
            df_export_final.columns = ['NOMBRE', 'X', 'Y', 'Z', 'CODIGO']
            csv_ajustados = df_export_final.to_csv(index=False, header=False).encode('utf-8')
            st.download_button(label="Descargar Hincas Ajustadas (.txt)", data=csv_ajustados, file_name='hincas_ajustadas.txt', mime='text/csv')
        else:
            st.info("No hay hincas que necesiten ser ajustadas para exportar.")

    if st.session_state.analysis_done and st.session_state.df_missing is not None and not st.session_state.df_missing.empty:
        csv_faltantes = st.session_state.df_missing.to_csv(index=False, header=True).encode('utf-8')
        st.download_button(label="Descargar Lista de Auxiliares Faltantes (.csv)", data=csv_faltantes, file_name='auxiliares_faltantes.csv', mime='text/csv')

# --- Área Principal para Mostrar Resultados ---
st.markdown("---")
st.header("Resultados del Análisis")

if not st.session_state.analysis_done:
    st.info("Carga los ficheros y pulsa 'Realizar Análisis' para ver los resultados aquí.")
else:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Resumen de Puntos Originales")
        st.code(st.session_state.summary_text)
        if not st.session_state.df_missing.empty:
            st.subheader("Seguidores con Auxiliares Faltantes")
            st.dataframe(st.session_state.df_missing)
        else:
            st.success("¡Excelente! No se encontraron seguidores con auxiliares faltantes.")
    with col2:
        st.subheader("Log del Proceso de Análisis")
        st.text_area("Log", value='\n'.join(st.session_state.log_messages), height=300, disabled=True)

    st.subheader("Vista Previa de Hincas con Coordenada Y Ajustada")
    df_preview = st.session_state.df_final[st.session_state.df_final['CODIGO'] == 'ajustado'].copy()
    
    if not df_preview.empty:
        df_preview['Y_ORIGINAL'] = df_preview['Y']
        df_preview['AJUSTE_Y'] = df_preview['Y_AJUSTADA'] - df_preview['Y_ORIGINAL']
        st.dataframe(
            df_preview[['NOMBRE', 'Y_ORIGINAL', 'Y_AJUSTADA', 'AJUSTE_Y']].rename(columns={
                'Y_ORIGINAL': 'Y Original', 'Y_AJUSTADA': 'Y Ajustada (Reducida)', 'AJUSTE_Y': 'Ajuste en Y (m)'
            }).style.format({
                'Y Original': '{:.3f}', 'Y Ajustada (Reducida)': '{:.3f}', 'Ajuste en Y (m)': '{:+.4f}'
            })
        )
    else:
        st.info("Ninguna hinca requirió ajuste de su coordenada Y.")