from io import BytesIO
from pathlib import Path
import re
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

st.set_page_config(page_title="Contentorização Marítima — Pilhas Dinâmicas 2D/3D", layout="wide")

PASTA_DADOS = Path(__file__).resolve().parent / "dados"
CAMINHO_CARACT = PASTA_DADOS / "CaracteristicasPallet.xlsx"
CAMINHO_COMP = PASTA_DADOS / "Compatibilidade.xlsx"
CAMINHO_EXEMPLO_CARGA = PASTA_DADOS / "volume_teste.xlsx"

PRESETS_CONTENTOR = {
    "20 pés": {"comp": 5900, "larg": 2350, "alt": 2390, "peso_max": 26000.0},
    "40 pés": {"comp": 12032, "larg": 2350, "alt": 2390, "peso_max": 26000.0},
    "Semi-trailer (PT)": {"comp": 13600, "larg": 2480, "alt": 2700, "peso_max": 24000.0},
    "Personalizado": {"comp": 0, "larg": 0, "alt": 0, "peso_max": 0.0},
}

CORES_PALETES = {
    "90x90": "#4E79A7",
    "120x120": "#F28E2B",
    "euro": "#59A14F",
    "euro+": "#EDC948",
    "120x278": "#B07AA1",
    "americana": "#FF9DA7",
}


def cor_palete(tipo_norm):
    return CORES_PALETES.get(tipo_norm, "#76B7B2")


def norm_tipo(val):
    s = str(val).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def init_state():
    if "tipo_contentor" not in st.session_state:
        st.session_state["tipo_contentor"] = "20 pés"
    p = PRESETS_CONTENTOR[st.session_state["tipo_contentor"]]
    st.session_state.setdefault("comp_mm", p["comp"])
    st.session_state.setdefault("larg_mm", p["larg"])
    st.session_state.setdefault("alt_mm", p["alt"])
    st.session_state.setdefault("peso_max_kg", p["peso_max"])


def on_change_tipo_contentor():
    p = PRESETS_CONTENTOR[st.session_state["tipo_contentor"]]
    st.session_state["comp_mm"] = p["comp"]
    st.session_state["larg_mm"] = p["larg"]
    st.session_state["alt_mm"] = p["alt"]
    st.session_state["peso_max_kg"] = p["peso_max"]


def is_nada_empilhado(item):
    if isinstance(item, dict):
        val = item.get("nadaempilhado", 0)
    else:
        val = item.get("nadaempilhado", 0) if "nadaempilhado" in item.index else 0
    if pd.isna(val):
        return False
    try:
        return int(float(val)) == 1
    except (ValueError, TypeError):
        return str(val).strip().lower() in ("1", "sim", "yes", "true")


def ler_bytes_e_df_ficheiro_base(caminho_disco, uploaded_file=None):
    if caminho_disco.exists():
        raw_bytes = caminho_disco.read_bytes()
        df = pd.read_excel(BytesIO(raw_bytes))
        return df, raw_bytes, "Automático (pasta dados/)"
    if uploaded_file is not None:
        raw_bytes = uploaded_file.getvalue()
        df = pd.read_excel(BytesIO(raw_bytes))
        return df, raw_bytes, "Manual (upload)"
    return None, None, None


def ler_bytes_exemplo_carga(caminho_exemplo):
    if caminho_exemplo.exists():
        return caminho_exemplo.read_bytes()
    return None


def carregar_dados(df_caract, df_comp, file_vol):
    df_caract = df_caract.copy()
    df_comp = df_comp.copy()
    df_vol = pd.read_excel(file_vol)

    df_caract.columns = [str(c).strip() for c in df_caract.columns]
    df_vol.columns = [str(c).strip() for c in df_vol.columns]

    if "Tipo Pallet" not in df_vol.columns:
        st.error("O ficheiro de volumes precisa da coluna 'Tipo Pallet'.")
        st.stop()
    if "Peso" not in df_vol.columns:
        st.error("O ficheiro de volumes precisa da coluna 'Peso'.")
        st.stop()

    if "ID" not in df_vol.columns:
        df_vol.insert(0, "ID", range(1, len(df_vol) + 1))

    col_nada = next((c for c in df_vol.columns if c.strip().lower() == "nadaempilhado"), None)
    if col_nada is not None:
        df_vol["nadaempilhado"] = df_vol[col_nada].apply(
            lambda v: 1 if is_nada_empilhado({"nadaempilhado": v}) else 0
        )
    else:
        df_vol["nadaempilhado"] = 0

    df_caract["Tipo_norm"] = df_caract["Tipo"].apply(norm_tipo)
    df_vol["Tipo_norm"] = df_vol["Tipo Pallet"].apply(norm_tipo)

    df_merged = pd.merge(
        df_vol,
        df_caract[["Tipo_norm", "Tipo", "Comprimento", "Largura", "AlturaMedia"]],
        on="Tipo_norm",
        how="left",
    )

    if df_merged["Comprimento"].isnull().any():
        em_falta = df_merged[df_merged["Comprimento"].isnull()]["Tipo Pallet"].unique()
        st.error(f"Tipos de palete não encontrados em CaracteristicasPallet: {list(em_falta)}")
        st.stop()

    return df_merged, df_comp


def preparar_matriz_compatibilidade(df_compat):
    comp_clean = df_compat.copy()
    comp_clean.columns = [norm_tipo(c) for c in comp_clean.columns]
    col_tipo = "tipo" if "tipo" in comp_clean.columns else comp_clean.columns[0]
    comp_clean["tipo_key"] = comp_clean[col_tipo].apply(norm_tipo)
    return comp_clean.drop_duplicates(subset=["tipo_key"]).set_index("tipo_key")


def _valor_compativel(cell):
    if pd.isna(cell):
        return False
    num = pd.to_numeric(cell, errors="coerce")
    if pd.notna(num):
        return int(round(float(num))) == 1
    txt = norm_tipo(cell)
    return txt in ("1", "sim", "s", "yes", "y", "true", "x", "ok")


def pode_empilhar(comp_matrix, base_norm, cima_norm):
    b_key = norm_tipo(base_norm)
    c_key = norm_tipo(cima_norm)
    if b_key not in comp_matrix.index:
        return False
    linha = comp_matrix.loc[b_key]
    if isinstance(linha, pd.DataFrame):
        linha = linha.iloc[0]
    if c_key in linha.index:
        return _valor_compativel(linha[c_key])
    c_nospace = c_key.replace(" ", "")
    for idx_col in linha.index:
        if norm_tipo(idx_col).replace(" ", "") == c_nospace:
            return _valor_compativel(linha[idx_col])
    return False


def _altura_camadas(camadas):
    return sum(int(x["AlturaMedia"]) for x in camadas)


def _peso_camadas(camadas):
    return sum(float(x["Peso"]) for x in camadas)


def _cabe_sobre_suporte(c_cima, l_cima, c_sup, l_sup, tolerancia_mm=50):
    return (
        (c_cima <= c_sup + tolerancia_mm and l_cima <= l_sup + tolerancia_mm)
        or (l_cima <= c_sup + tolerancia_mm and c_cima <= l_sup + tolerancia_mm)
    )


def _pilha_valida(camadas, comp_matrix, alt_cont, limite_niveis=None):
    if not camadas:
        return False
    if limite_niveis is not None and len(camadas) > limite_niveis:
        return False
    if _altura_camadas(camadas) > alt_cont:
        return False
    for i, item in enumerate(camadas):
        if is_nada_empilhado(item) and i < len(camadas) - 1:
            return False
        if i > 0:
            baixo = camadas[i - 1]
            if not pode_empilhar(comp_matrix, baixo["Tipo_norm"], item["Tipo_norm"]):
                return False
            if not _cabe_sobre_suporte(
                int(item["Comprimento"]),
                int(item["Largura"]),
                int(baixo["Comprimento"]),
                int(baixo["Largura"]),
            ):
                return False
    return True


def _recalcular_pilha(pilha):
    camadas = pilha["camadas"]
    pilha["num_niveis"] = len(camadas)
    pilha["altura_total"] = _altura_camadas(camadas)
    pilha["peso_total"] = _peso_camadas(camadas)
    pilha["comp_base"] = int(camadas[0]["Comprimento"])
    pilha["larg_base"] = int(camadas[0]["Largura"])
    pilha["area_base"] = pilha["comp_base"] * pilha["larg_base"]
    pilha["id_base"] = int(camadas[0]["ID"])


def _inserir_item_em_pilha(item, pilha, comp_matrix, alt_cont, limite_niveis=None):
    camadas = pilha["camadas"]
    if not is_nada_empilhado(camadas[-1]):
        cand = camadas + [item]
        if _pilha_valida(cand, comp_matrix, alt_cont, limite_niveis):
            pilha["camadas"] = cand
            _recalcular_pilha(pilha)
            return True

    if not is_nada_empilhado(item) and len(camadas) >= 1 and is_nada_empilhado(camadas[-1]):
        pos = len(camadas) - 1
        cand = camadas[:pos] + [item] + camadas[pos:]
        if _pilha_valida(cand, comp_matrix, alt_cont, limite_niveis):
            pilha["camadas"] = cand
            _recalcular_pilha(pilha)
            return True

    return False


def construir_pilhas_compativeis(df_itens, comp_matrix, alt_cont, limite_niveis=None, ordenar_maior=True):
    if ordenar_maior:
        itens = df_itens.sort_values(by=["Area", "Lado_Max", "ID"], ascending=[False, False, True]).copy()
    else:
        itens = df_itens.sort_values(by=["ID"], ascending=[True]).copy()

    normais = [r.to_dict() for _, r in itens[~itens.apply(is_nada_empilhado, axis=1)].iterrows()]
    especiais_ne = [r.to_dict() for _, r in itens[itens.apply(is_nada_empilhado, axis=1)].iterrows()]

    pilhas = []
    usadas_norm = set()

    for i_base, base_item in enumerate(normais):
        if i_base in usadas_norm:
            continue
        if int(base_item["AlturaMedia"]) > alt_cont:
            continue

        usadas_norm.add(i_base)
        camadas = [base_item]

        while limite_niveis is None or len(camadas) < limite_niveis:
            topo = camadas[-1]
            if is_nada_empilhado(topo):
                break
            melhor_i = None
            for i_cand, cand_item in enumerate(normais):
                if i_cand in usadas_norm:
                    continue
                if _pilha_valida(camadas + [cand_item], comp_matrix, alt_cont, limite_niveis):
                    melhor_i = i_cand
                    break
            if melhor_i is not None:
                usadas_norm.add(melhor_i)
                camadas.append(normais[melhor_i])
            else:
                break

        pilha = {"camadas": camadas}
        _recalcular_pilha(pilha)
        pilhas.append(pilha)

    for ne_item in especiais_ne:
        if int(ne_item["AlturaMedia"]) > alt_cont:
            continue

        colocado = False
        for p in sorted(pilhas, key=lambda x: (x["num_niveis"], x["altura_total"], x["id_base"])):
            if is_nada_empilhado(p["camadas"][-1]):
                continue
            if _pilha_valida(p["camadas"] + [ne_item], comp_matrix, alt_cont, limite_niveis):
                p["camadas"].append(ne_item)
                _recalcular_pilha(p)
                colocado = True
                break

        if not colocado:
            for p in sorted(pilhas, key=lambda x: (-x["num_niveis"], -x["altura_total"])):
                if len(p["camadas"]) < 2 or is_nada_empilhado(p["camadas"][-1]):
                    continue
                camadas_sem_topo = p["camadas"][:-1]
                topo_removido = p["camadas"][-1]
                if _pilha_valida(camadas_sem_topo + [ne_item], comp_matrix, alt_cont, limite_niveis):
                    p["camadas"] = camadas_sem_topo + [ne_item]
                    _recalcular_pilha(p)

                    recolocado = False
                    for p2 in sorted(pilhas, key=lambda x: (x["num_niveis"], x["altura_total"])):
                        if p2 is p or is_nada_empilhado(p2["camadas"][-1]):
                            continue
                        if _pilha_valida(p2["camadas"] + [topo_removido], comp_matrix, alt_cont, limite_niveis):
                            p2["camadas"].append(topo_removido)
                            _recalcular_pilha(p2)
                            recolocado = True
                            break

                    if not recolocado:
                        nova_p = {"camadas": [topo_removido]}
                        _recalcular_pilha(nova_p)
                        pilhas.append(nova_p)

                    colocado = True
                    break

        if not colocado:
            nova_p = {"camadas": [ne_item]}
            _recalcular_pilha(nova_p)
            pilhas.append(nova_p)

    for p_solta in list(pilhas):
        if len(p_solta["camadas"]) == 1 and p_solta in pilhas:
            item_solto = p_solta["camadas"][0]
            for p_alvo in sorted(pilhas, key=lambda x: (x["num_niveis"], x["altura_total"])):
                if p_alvo is p_solta:
                    continue
                if _inserir_item_em_pilha(item_solto, p_alvo, comp_matrix, alt_cont, limite_niveis):
                    pilhas.remove(p_solta)
                    break

    return pilhas


def sobrepoe_2d(x1, y1, w1, h1, x2, y2, w2, h2):
    return (x1 < x2 + w2) and (x1 + w1 > x2) and (y1 < y2 + h2) and (y1 + h1 > y2)


def _orientacoes_para_espaco(c_orig, l_orig, max_w, max_h):
    candidatas = [(c_orig, l_orig, "Normal")]
    if c_orig != l_orig:
        candidatas.append((l_orig, c_orig, "Rodada 90°"))
    return [(dx, dy, nome) for dx, dy, nome in candidatas if dx <= max_w and dy <= max_h]


def _encontrar_encaixe(colunas, comp_cont, larg_cont, c_orig, l_orig, preferir_frente=False):
    cand_x = {0}
    cand_y = {0}
    for col in colunas:
        cand_x.add(col["x"] + col["dx"])
        cand_y.add(col["y"] + col["dy"])

    melhor = None
    melhor_score = None

    for dim_x, dim_y, orient_nome in _orientacoes_para_espaco(c_orig, l_orig, comp_cont, larg_cont):
        for ax in sorted(cand_x):
            if ax + dim_x > comp_cont:
                continue
            for ay in sorted(cand_y):
                if ay + dim_y > larg_cont:
                    continue
                if any(
                    sobrepoe_2d(ax, ay, dim_x, dim_y, col["x"], col["y"], col["dx"], col["dy"])
                    for col in colunas
                ):
                    continue
                sobra_y = larg_cont - (ay + dim_y)
                score = (-ax, ay, sobra_y, dim_x) if preferir_frente else (ax, ay, sobra_y, dim_x)
                if melhor_score is None or score < melhor_score:
                    melhor_score = score
                    melhor = (ax, ay, dim_x, dim_y, orient_nome)

    return melhor


def compactar_para_fundo(colunas_alocadas):
    ordenadas = sorted(colunas_alocadas, key=lambda c: (c["x"], c["y"]))
    for col in ordenadas:
        dx, dy, y = col["dx"], col["dy"], col["y"]
        limite_x = 0
        for outra in ordenadas:
            if outra is col:
                continue
            y_overlap = (y < outra["y"] + outra["dy"]) and (y + dy > outra["y"])
            if y_overlap and (outra["x"] + outra["dx"] <= col["x"]):
                limite_x = max(limite_x, outra["x"] + outra["dx"])

        candidatos = sorted(
            {limite_x}
            | {
                outra["x"] + outra["dx"]
                for outra in ordenadas
                if outra is not col and limite_x <= outra["x"] + outra["dx"] < col["x"]
            }
        )
        for cx in candidatos:
            if not any(
                sobrepoe_2d(cx, y, dx, dy, o["x"], o["y"], o["dx"], o["dy"])
                for o in ordenadas
                if o is not col
            ):
                col["x"] = cx
                break


def nivelar_e_aproveitar_piso(colunas, comp_matrix, comp_cont, larg_cont, alt_cont, limite_niveis=None):
    if not colunas:
        return

    while True:
        doadoras = sorted(
            [c for c in colunas if len(c["pilha"]["camadas"]) >= 2],
            key=lambda c: (-len(c["pilha"]["camadas"]), -c["x"], -c["y"]),
        )
        moveu = False

        for doadora in doadoras:
            camada_topo = doadora["pilha"]["camadas"][-1]
            c_orig = int(camada_topo["Comprimento"])
            l_orig = int(camada_topo["Largura"])
            alt_topo = int(camada_topo["AlturaMedia"])

            if alt_topo > alt_cont:
                continue

            encaixe = _encontrar_encaixe(colunas, comp_cont, larg_cont, c_orig, l_orig, preferir_frente=False)
            if encaixe is not None:
                ax, ay, dx, dy, orient_nome = encaixe
                doadora["pilha"]["camadas"].pop()
                _recalcular_pilha(doadora["pilha"])

                nova_pilha = {"camadas": [camada_topo]}
                _recalcular_pilha(nova_pilha)
                nova_col = {
                    "x": ax,
                    "y": ay,
                    "dx": dx,
                    "dy": dy,
                    "orient": orient_nome,
                    "pilha": nova_pilha,
                }
                colunas.append(nova_col)

                if not is_nada_empilhado(nova_col["pilha"]["camadas"][-1]):
                    teto_novo = 2 if limite_niveis is None else min(2, limite_niveis)
                    for outra_doadora in sorted(
                        [c for c in colunas if c is not nova_col and len(c["pilha"]["camadas"]) >= 2],
                        key=lambda c: (-len(c["pilha"]["camadas"]), -c["x"]),
                    ):
                        if len(nova_col["pilha"]["camadas"]) >= teto_novo:
                            break
                        if is_nada_empilhado(nova_col["pilha"]["camadas"][-1]):
                            break
                        cand_topo = outra_doadora["pilha"]["camadas"][-1]
                        if _pilha_valida(
                            nova_col["pilha"]["camadas"] + [cand_topo],
                            comp_matrix,
                            alt_cont,
                            limite_niveis,
                        ):
                            outra_doadora["pilha"]["camadas"].pop()
                            _recalcular_pilha(outra_doadora["pilha"])
                            nova_col["pilha"]["camadas"].append(cand_topo)
                            _recalcular_pilha(nova_col["pilha"])

                compactar_para_fundo(colunas)
                moveu = True
                break

        if not moveu:
            break


def _tentar_empilhar_em_colunas_existentes(item, colunas, comp_matrix, alt_cont, limite_niveis=None):
    cols_ordenadas = sorted(
        colunas,
        key=lambda c: (c["x"], c["y"], len(c["pilha"]["camadas"]), c["pilha"]["altura_total"]),
    )
    for col in cols_ordenadas:
        if _inserir_item_em_pilha(item, col["pilha"], comp_matrix, alt_cont, limite_niveis):
            return True
    return False


def simular_contentor(
    df_volumes,
    df_compat,
    comp_cont,
    larg_cont,
    alt_cont,
    peso_max,
    limite_niveis=None,
    ordenar_maior=True,
    priorizar_pilha=True,
    nivelar_pilhas=False,
):
    comp_matrix = preparar_matriz_compatibilidade(df_compat)
    itens = df_volumes.copy()
    itens["Area"] = itens["Comprimento"] * itens["Largura"]
    itens["Lado_Max"] = itens[["Comprimento", "Largura"]].max(axis=1)

    pilhas = construir_pilhas_compativeis(
        itens, comp_matrix, alt_cont, limite_niveis=limite_niveis, ordenar_maior=ordenar_maior
    )

    if priorizar_pilha and ordenar_maior:
        pilhas.sort(key=lambda p: (-p["num_niveis"], -p["area_base"], p["id_base"]))
    elif priorizar_pilha:
        pilhas.sort(key=lambda p: (-p["num_niveis"], p["id_base"]))
    elif ordenar_maior:
        pilhas.sort(key=lambda p: (-p["area_base"], p["id_base"]))
    else:
        pilhas.sort(key=lambda p: p["id_base"])

    peso_acumulado = 0.0
    colunas = []
    itens_pendentes = []

    for pilha in pilhas:
        if peso_max > 0 and (peso_acumulado + pilha["peso_total"]) > peso_max:
            itens_pendentes.extend(pilha["camadas"])
            continue

        encaixe = _encontrar_encaixe(
            colunas, comp_cont, larg_cont, pilha["comp_base"], pilha["larg_base"], preferir_frente=False
        )

        if encaixe is not None:
            ax, ay, dim_x, dim_y, orient_nome = encaixe
            peso_acumulado += pilha["peso_total"]
            colunas.append({
                "x": ax,
                "y": ay,
                "dx": dim_x,
                "dy": dim_y,
                "orient": orient_nome,
                "pilha": pilha,
            })
            compactar_para_fundo(colunas)
        else:
            for camada in pilha["camadas"]:
                if peso_max > 0 and (peso_acumulado + float(camada["Peso"])) > peso_max:
                    itens_pendentes.append(camada)
                    continue
                if _tentar_empilhar_em_colunas_existentes(
                    camada, colunas, comp_matrix, alt_cont, limite_niveis
                ):
                    peso_acumulado += float(camada["Peso"])
                else:
                    itens_pendentes.append(camada)

    ainda_pendentes = []
    for item in itens_pendentes:
        if peso_max > 0 and (peso_acumulado + float(item["Peso"])) > peso_max:
            ainda_pendentes.append(item)
            continue
        if _tentar_empilhar_em_colunas_existentes(
            item, colunas, comp_matrix, alt_cont, limite_niveis
        ):
            peso_acumulado += float(item["Peso"])
        else:
            ainda_pendentes.append(item)

    if nivelar_pilhas:
        nivelar_e_aproveitar_piso(colunas, comp_matrix, comp_cont, larg_cont, alt_cont, limite_niveis=limite_niveis)

    nao_alocados = []
    for c in ainda_pendentes:
        nao_alocados.append({
            "ID": int(c["ID"]),
            "Tipo Pallet": c["Tipo Pallet"],
            "Dimensões (mm)": f"{int(c['Comprimento'])} x {int(c['Largura'])}",
            "Altura (mm)": int(c["AlturaMedia"]),
            "Peso (kg)": float(c["Peso"]),
            "Nada Empilhado": 1 if is_nada_empilhado(c) else 0,
            "Motivo": "Excede o peso máximo permitido"
            if (peso_max > 0 and (peso_acumulado + float(c["Peso"])) > peso_max)
            else "Sem espaço livre ou compatibilidade para empilhar no contentor",
        })

    alocados = []
    for col in colunas:
        z_atual = 0
        base_id_ref = "-"
        for niv_idx, c in enumerate(col["pilha"]["camadas"]):
            alt_c = int(c["AlturaMedia"])
            cc = int(c["Comprimento"])
            lc = int(c["Largura"])

            if _cabe_sobre_suporte(cc, lc, col["dx"], col["dy"]):
                if col["orient"] == "Normal" and cc <= col["dx"] + 50 and lc <= col["dy"] + 50:
                    dx_c, dy_c, or_c = cc, lc, "Normal"
                elif lc <= col["dx"] + 50 and cc <= col["dy"] + 50:
                    dx_c, dy_c, or_c = lc, cc, "Rodada 90°"
                else:
                    dx_c, dy_c, or_c = cc, lc, "Normal"
            else:
                dx_c, dy_c, or_c = col["dx"], col["dy"], col["orient"]

            alocados.append({
                "Nível": niv_idx,
                "Base ID": base_id_ref if niv_idx > 0 else "-",
                "ID": int(c["ID"]),
                "Tipo Pallet": c["Tipo Pallet"],
                "Tipo_norm": c["Tipo_norm"],
                "Nada Empilhado": 1 if is_nada_empilhado(c) else 0,
                "Orientação": or_c,
                "Dim X (mm)": dx_c,
                "Dim Y (mm)": dy_c,
                "Altura (mm)": alt_c,
                "Pos X (mm)": col["x"],
                "Pos Y (mm)": col["y"],
                "Fim X (mm)": col["x"] + dx_c,
                "Fim Y (mm)": col["y"] + dy_c,
                "Base Z (mm)": z_atual,
                "Topo Z (mm)": z_atual + alt_c,
                "Peso (kg)": float(c["Peso"]),
            })
            if niv_idx == 0:
                base_id_ref = int(c["ID"])
            z_atual += alt_c

    return pd.DataFrame(alocados), pd.DataFrame(nao_alocados), peso_acumulado


def desenhar_planta_2d(df_total, comp_cont, larg_cont, tipo_cont, filtro_nivel):
    fig, ax = plt.subplots(figsize=(14, 4.4))

    rect_cont = patches.Rectangle(
        (0, 0), comp_cont, larg_cont,
        linewidth=2.5, edgecolor="#222222", facecolor="#F4F6F8", zorder=1
    )
    ax.add_patch(rect_cont)

    ax.text(-180, larg_cont / 2, "FUNDO\n(X=0)", va="center", ha="right",
            fontsize=10, fontweight="bold", color="#333333")
    ax.text(comp_cont + 180, larg_cont / 2, "PORTA\n(Frente)", va="center", ha="left",
            fontsize=10, fontweight="bold", color="#B22222")

    if not df_total.empty:
        niveis_presentes = sorted(df_total["Nível"].unique())
        max_niv_presente = max(niveis_presentes)
        for niv in niveis_presentes:
            if filtro_nivel != "Todos os níveis" and f"Nível {niv}" != filtro_nivel:
                continue

            sub = df_total[df_total["Nível"] == niv]
            alpha = 0.92 if (filtro_nivel != "Todos os níveis" or niv == max_niv_presente) else max(0.35, 0.85 - 0.15 * (max_niv_presente - niv))
            inset = niv * 24 if filtro_nivel == "Todos os níveis" else 0

            for _, row in sub.iterrows():
                ne_flag = int(row.get("Nada Empilhado", 0)) == 1
                cor = cor_palete(row["Tipo_norm"])
                rx = row["Pos X (mm)"] + inset
                ry = row["Pos Y (mm)"] + inset
                rw = max(120, row["Dim X (mm)"] - 2 * inset)
                rh = max(120, row["Dim Y (mm)"] - 2 * inset)

                rect = patches.Rectangle(
                    (rx, ry), rw, rh,
                    linewidth=1.5 + 0.2 * min(niv, 5),
                    edgecolor="#111111",
                    facecolor=cor,
                    hatch="///" if ne_flag else None,
                    alpha=alpha,
                    zorder=2 + niv,
                )
                ax.add_patch(rect)

                mostrar_texto = (filtro_nivel != "Todos os níveis") or (niv == max_niv_presente)
                if mostrar_texto:
                    cx = rx + rw / 2
                    cy = ry + rh / 2
                    rot = " [R]" if row["Orientação"] == "Rodada 90°" else ""
                    ne_txt = " [NE]" if ne_flag else ""
                    base_txt = f" s/{row['Base ID']}" if row["Base ID"] != "-" else ""
                    ax.text(
                        cx, cy,
                        f"N{niv} ID {row['ID']}{base_txt}{ne_txt}\n{row['Tipo Pallet']}{rot}\nZ:{row['Base Z (mm)']}-{row['Topo Z (mm)']}mm",
                        ha="center", va="center", fontsize=6.4, fontweight="bold", color="#111111", zorder=10 + niv
                    )

    margem_x = max(500, comp_cont * 0.05)
    ax.set_xlim(-margem_x, comp_cont + margem_x + 150)
    ax.set_ylim(-250, larg_cont + 350)
    ax.set_aspect("equal")
    ax.set_xlabel("Comprimento do Contentor (mm)")
    ax.set_ylabel("Largura (mm)")
    ax.set_title(
        f"Planta 2D — {tipo_cont} ({comp_cont} x {larg_cont} mm) | {filtro_nivel}",
        fontsize=11.5, fontweight="bold", pad=12
    )
    ax.grid(True, linestyle="--", alpha=0.3, zorder=0)
    plt.tight_layout()
    return fig


def _faces_caixa_3d(x, y, z, dx, dy, dz):
    x0, x1 = x, x + dx
    y0, y1 = y, y + dy
    z0, z1 = z, z + dz
    return [
        [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
    ]


def desenhar_vista_3d(df_total, comp_cont, larg_cont, alt_cont, tipo_cont, elev=22, azim=-58):
    fig = plt.figure(figsize=(14, 5.6))
    ax = fig.add_subplot(111, projection="3d")

    cantos = [
        ((0, comp_cont), (0, 0), (0, 0)),
        ((0, comp_cont), (larg_cont, larg_cont), (0, 0)),
        ((0, comp_cont), (0, 0), (alt_cont, alt_cont)),
        ((0, comp_cont), (larg_cont, larg_cont), (alt_cont, alt_cont)),
        ((0, 0), (0, larg_cont), (0, 0)),
        ((comp_cont, comp_cont), (0, larg_cont), (0, 0)),
        ((0, 0), (0, larg_cont), (alt_cont, alt_cont)),
        ((comp_cont, comp_cont), (0, larg_cont), (alt_cont, alt_cont)),
        ((0, 0), (0, 0), (0, alt_cont)),
        ((comp_cont, comp_cont), (0, 0), (0, alt_cont)),
        ((0, 0), (larg_cont, larg_cont), (0, alt_cont)),
        ((comp_cont, comp_cont), (larg_cont, larg_cont), (0, alt_cont)),
    ]
    for xs, ys, zs in cantos:
        ax.plot(xs, ys, zs, color="#444444", linewidth=1.1, linestyle="--", alpha=0.65)

    piso_x = [0, comp_cont, comp_cont, 0]
    piso_y = [0, 0, larg_cont, larg_cont]
    piso_z = [0, 0, 0, 0]
    ax.plot_trisurf(piso_x, piso_y, piso_z, color="#E8EEF3", alpha=0.25)

    if not df_total.empty:
        for _, row in df_total.iterrows():
            ne_flag = int(row.get("Nada Empilhado", 0)) == 1
            cor = cor_palete(row["Tipo_norm"])
            faces = _faces_caixa_3d(
                row["Pos X (mm)"],
                row["Pos Y (mm)"],
                row["Base Z (mm)"],
                row["Dim X (mm)"],
                row["Dim Y (mm)"],
                row["Altura (mm)"],
            )
            poly = Poly3DCollection(
                faces,
                facecolors=cor,
                edgecolors="#111111",
                linewidths=0.9,
                hatch="///" if ne_flag else None,
                alpha=0.86,
            )
            ax.add_collection3d(poly)

    z_max = max(alt_cont, int(df_total["Topo Z (mm)"].max()) + 150 if not df_total.empty else alt_cont)
    ax.set_xlim(0, comp_cont)
    ax.set_ylim(0, larg_cont)
    ax.set_zlim(0, z_max)
    ax.set_box_aspect((comp_cont, larg_cont, z_max))

    ax.set_xlabel("Comprimento X (mm) [0=Fundo -> Porta]")
    ax.set_ylabel("Largura Y (mm)")
    ax.set_zlabel("Altura Z (mm)")
    ax.set_title(
        f"Vista 3D — {tipo_cont} ({comp_cont} x {larg_cont} x {alt_cont} mm)",
        fontsize=11.5, fontweight="bold", pad=12
    )
    ax.view_init(elev=elev, azim=azim)
    plt.tight_layout()
    return fig


init_state()

st.title("📦 Contentorização Marítima — Pilhas Dinâmicas (2D + 3D)")
st.markdown("Adiciona níveis dinamicamente conforme a altura útil do contentor, compatibilidade, restrição `nadaempilhado` e volumes disponíveis, do **fundo para a porta**.")

with st.sidebar:
    st.header("Parâmetros do Contentor")

    tipo_cont = st.selectbox(
        "Tipo de contentor",
        options=list(PRESETS_CONTENTOR.keys()),
        key="tipo_contentor",
        on_change=on_change_tipo_contentor,
    )

    comp_cont = st.number_input("Comprimento interno (mm)", min_value=0, step=10, key="comp_mm")
    larg_cont = st.number_input("Largura interna (mm)", min_value=0, step=10, key="larg_mm")
    alt_cont = st.number_input("Altura interna (mm)", min_value=0, step=10, key="alt_mm")
    peso_max = st.number_input("Peso Máximo Permitido (kg)", min_value=0.0, step=100.0, key="peso_max_kg")

    usar_limite_niveis = st.checkbox(
        "Impor limite manual de níveis",
        value=False,
        help="Se desligado, o algoritmo empilha livremente até ao limite de altura do contentor e volumes compatíveis.",
    )
    limite_niveis_val = None
    if usar_limite_niveis:
        limite_niveis_val = st.number_input("Máximo de níveis", min_value=1, max_value=30, value=3, step=1)

    priorizar_pilha = st.checkbox("Pilhas mais altas/completas primeiro (fundo)", value=True)
    ordenar_maior = st.checkbox("Priorizar bases/paletes maiores", value=True)
    nivelar_pilhas = st.checkbox("Nivelar pilhas altas e aproveitar espaço livre no solo", value=True)

    st.header("Dados de Entrada")
    f_caract_up = None
    if not CAMINHO_CARACT.exists():
        st.caption("Ficheiro automático não encontrado em `dados/CaracteristicasPallet.xlsx`.")
        f_caract_up = st.file_uploader("CaracteristicasPallet.xlsx", type=["xlsx"], key="up_caract")

    f_comp_up = None
    if not CAMINHO_COMP.exists():
        st.caption("Ficheiro automático não encontrado em `dados/Compatibilidade.xlsx`.")
        f_comp_up = st.file_uploader("Compatibilidade.xlsx", type=["xlsx"], key="up_comp")

    f_vol = st.file_uploader("Ficheiro de carga (ex.: volume_teste.xlsx)", type=["xlsx"])

    bytes_exemplo = ler_bytes_exemplo_carga(CAMINHO_EXEMPLO_CARGA)
    st.markdown("**Descarregue o ficheiro de exemplo:**")
    if bytes_exemplo is not None:
        st.download_button(
            label="⬇️ Exemplo de Carga",
            data=bytes_exemplo,
            file_name="volume_teste.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.caption("Coloque `volume_teste.xlsx` em `dados/` para disponibilizar o download.")

    df_caract_base, bytes_caract, origem_caract = ler_bytes_e_df_ficheiro_base(CAMINHO_CARACT, f_caract_up)
    df_comp_base, bytes_comp, origem_comp = ler_bytes_e_df_ficheiro_base(CAMINHO_COMP, f_comp_up)

    if bytes_caract is not None or bytes_comp is not None:
        st.subheader("Ficheiros Base")
        if bytes_caract is not None:
            st.caption(f"CaracteristicasPallet: {origem_caract}")
            st.download_button(
                label="⬇️ Baixar CaracteristicasPallet.xlsx",
                data=bytes_caract,
                file_name="CaracteristicasPallet.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        if bytes_comp is not None:
            st.caption(f"Compatibilidade: {origem_comp}")
            st.download_button(
                label="⬇️ Baixar Compatibilidade.xlsx",
                data=bytes_comp,
                file_name="Compatibilidade.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

if df_caract_base is not None and df_comp_base is not None and f_vol is not None:
    df_volumes, df_compat = carregar_dados(df_caract_base, df_comp_base, f_vol)
    df_total, df_nao, peso_total = simular_contentor(
        df_volumes,
        df_compat,
        comp_cont,
        larg_cont,
        alt_cont,
        peso_max,
        limite_niveis=limite_niveis_val,
        ordenar_maior=ordenar_maior,
        priorizar_pilha=priorizar_pilha,
        nivelar_pilhas=nivelar_pilhas,
    )

    df_n0 = df_total[df_total["Nível"] == 0] if not df_total.empty else pd.DataFrame()
    area_cont = comp_cont * larg_cont
    area_n0 = (df_n0["Dim X (mm)"] * df_n0["Dim Y (mm)"]).sum() if not df_n0.empty else 0
    ocupacao_n0_pct = (area_n0 / area_cont) * 100 if area_cont > 0 else 0
    comp_usado = df_n0["Fim X (mm)"].max() if not df_n0.empty else 0

    niveis_atingidos = sorted(df_total["Nível"].unique()) if not df_total.empty else [0]
    contagem_niveis = " | ".join([f"N{n}: {int((df_total['Nível'] == n).sum())}" for n in niveis_atingidos]) if not df_total.empty else "N0: 0"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Volumes Alocados", f"{len(df_total)} / {len(df_volumes)} ({contagem_niveis})")
    c2.metric("Ocupação de Área (Nível 0)", f"{ocupacao_n0_pct:.1f}%")
    c3.metric("Comprimento Ocupado", f"{comp_usado} / {comp_cont} mm")
    c4.metric("Peso Total Contentor", f"{peso_total:,.0f} / {peso_max:,.0f} kg" if peso_max > 0 else f"{peso_total:,.0f} kg")

    st.subheader("🗺️ Esquema Visual 2D (Planta)")
    opcoes_nivel = ["Todos os níveis"] + [f"Nível {n}" for n in niveis_atingidos]
    filtro_nivel = st.radio("Camada 2D a visualizar:", options=opcoes_nivel, horizontal=True)
    st.pyplot(desenhar_planta_2d(df_total, comp_cont, larg_cont, tipo_cont, filtro_nivel))

    st.subheader("🧊 Esquema Visual 3D do Contentor")
    col_v1, col_v2 = st.columns(2)
    elev_3d = col_v1.slider("Ângulo Vertical (Elevação 3D)", min_value=5, max_value=75, value=22, step=1)
    azim_3d = col_v2.slider("Ângulo Horizontal (Azimute 3D)", min_value=-135, max_value=45, value=-58, step=2)
    st.pyplot(desenhar_vista_3d(df_total, comp_cont, larg_cont, alt_cont, tipo_cont, elev=elev_3d, azim=azim_3d))

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Tabela Detalhada Completa",
        "⏳ Sobras",
        "📋 Compatibilidade",
        "📏 Características Paletes",
    ])

    with tab1:
        if df_total.empty:
            st.info("Nenhum volume alocado.")
        else:
            cols_show = [
                "Nível", "ID", "Base ID", "Tipo Pallet", "Nada Empilhado", "Orientação",
                "Dim X (mm)", "Dim Y (mm)", "Altura (mm)",
                "Pos X (mm)", "Pos Y (mm)", "Fim X (mm)", "Fim Y (mm)",
                "Base Z (mm)", "Topo Z (mm)", "Peso (kg)"
            ]
            st.dataframe(df_total[cols_show], use_container_width=True)

    with tab2:
        if df_nao.empty:
            st.success("Todos os volumes foram alocados!")
        else:
            st.warning(f"Ficaram {len(df_nao)} volumes por alocar.")
            st.dataframe(df_nao, use_container_width=True)

    with tab3:
        st.dataframe(df_compat, use_container_width=True)

    with tab4:
        cols_caract_show = [c for c in df_caract_base.columns if c != "Tipo_norm"]
        st.dataframe(df_caract_base[cols_caract_show], use_container_width=True)
else:
    st.info("Coloca `CaracteristicasPallet.xlsx` e `Compatibilidade.xlsx` na pasta `dados/` (junto ao script) e carrega o ficheiro de carga na barra lateral para iniciar.")