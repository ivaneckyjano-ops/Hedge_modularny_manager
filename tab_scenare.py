#!/usr/bin/env python3
"""
Záložka: Scenáre
Scenárová analýza - What-if simulácie
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import sys
import os

# Import scenario simulator
try:
    sys.path.insert(0, '/home/narbon/Aplikácie/tws-webapp/scripts')
    from scenario_simulator import ScenarioSimulator
    SCENARIO_AVAILABLE = True
except ImportError:
    SCENARIO_AVAILABLE = False

# Import export utils
try:
    from export_utils import export_strategy, ExportUtils
    EXPORT_AVAILABLE = True
except ImportError:
    EXPORT_AVAILABLE = False


def generate_scenarios(state):
    """Generuje scenáre pre aktuálnu stratégiu"""
    if not SCENARIO_AVAILABLE:
        messagebox.showerror("Chyba", "ScenarioSimulator nie je dostupný")
        return
    
    if not hasattr(state, 'last_result') or not state.last_result:
        messagebox.showwarning("Chyba", "Najprv nájdite hedge alebo spustite optimalizáciu")
        return
    
    if not hasattr(state, 'scenario_info_label'):
        return
    
    state.scenario_info_label.config(text="Generujem scenáre...")
    
    try:
        result = state.last_result
        simulator = ScenarioSimulator(result)
        state.scenarios = simulator.generate_scenarios()
        
        # Zobraz scenáre
        display_scenarios(state)
        
        state.scenario_info_label.config(text=f"✅ Vygenerovaných {len(state.scenarios)} scenárov")
    except Exception as e:
        messagebox.showerror("Chyba", f"Nepodarilo sa vygenerovať scenáre:\n{e}")
        state.scenario_info_label.config(text="Chyba pri generovaní scenárov")


def display_scenarios(state):
    """Zobrazí scenáre v matici a textovom poli"""
    if not hasattr(state, 'matrix_tree') or not hasattr(state, 'scenarios_text'):
        return
    
    if not state.scenarios:
        return
    
    # Vyčisti maticu
    for item in state.matrix_tree.get_children():
        state.matrix_tree.delete(item)
    
    # Vyčisti text
    state.scenarios_text.delete(1.0, tk.END)
    
    # Získaj unikátne ceny a časy
    prices = sorted(set(s['price'] for s in state.scenarios))
    times = sorted(set(s['time'] for s in state.scenarios))
    
    # Nastav stĺpce
    columns = ['Cena'] + [f"T+{t}d" for t in times]
    state.matrix_tree['columns'] = columns
    state.matrix_tree.heading('#0', text='')
    state.matrix_tree.column('#0', width=0, stretch=False)
    
    for col in columns:
        state.matrix_tree.heading(col, text=col)
        state.matrix_tree.column(col, width=80, anchor='center')
    
    # Naplň maticu
    for price in prices:
        values = [f"${price:.2f}"]
        for time in times:
            scenario = next((s for s in state.scenarios if s['price'] == price and s['time'] == time), None)
            if scenario:
                pl = scenario.get('pl', 0)
                values.append(f"${pl:.2f}")
            else:
                values.append("—")
        
        item = state.matrix_tree.insert('', 'end', values=values)
        
        # Farba podľa P/L
        for i, val in enumerate(values[1:], 1):
            try:
                pl = float(val.replace('$', '').replace('—', '0'))
                if pl > 0:
                    state.matrix_tree.set(item, columns[i], val)
                    # Zelená pre profit
                    state.matrix_tree.item(item, tags=('profit',))
                elif pl < 0:
                    # Červená pre loss
                    state.matrix_tree.item(item, tags=('loss',))
                else:
                    # Žltá pre neutral
                    state.matrix_tree.item(item, tags=('neutral',))
            except:
                pass
    
    # Nastav farby
    state.matrix_tree.tag_configure('profit', background='#90EE90')
    state.matrix_tree.tag_configure('loss', background='#FFB6C1')
    state.matrix_tree.tag_configure('neutral', background='#FFFACD')
    
    # Textový výstup
    state.scenarios_text.insert(tk.END, "SCENÁROVÁ ANALÝZA\n")
    state.scenarios_text.insert(tk.END, "=" * 50 + "\n\n")
    
    for scenario in state.scenarios:
        state.scenarios_text.insert(tk.END, f"Cena: ${scenario['price']:.2f}, Čas: T+{scenario['time']}d\n")
        state.scenarios_text.insert(tk.END, f"  P/L: ${scenario.get('pl', 0):.2f}\n")
        if 'details' in scenario:
            state.scenarios_text.insert(tk.END, f"  {scenario['details']}\n")
        state.scenarios_text.insert(tk.END, "\n")


def export_scenarios(state):
    """Exportuje scenáre do súboru"""
    if not hasattr(state, 'scenarios') or not state.scenarios:
        messagebox.showwarning("Chyba", "Najprv vygenerujte scenáre")
        return
    
    if not EXPORT_AVAILABLE:
        messagebox.showerror("Chyba", "ExportUtils nie je dostupný")
        return
    
    filename = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON", "*.json"), ("CSV", "*.csv"), ("Všetky súbory", "*.*")]
    )
    
    if filename:
        try:
            if filename.endswith('.json'):
                import json
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(state.scenarios, f, indent=2, ensure_ascii=False)
            elif filename.endswith('.csv'):
                import csv
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['price', 'time', 'pl', 'details'])
                    writer.writeheader()
                    writer.writerows(state.scenarios)
            
            messagebox.showinfo("Úspech", f"Scenáre exportované do {filename}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa exportovať scenáre:\n{e}")


def create_scenarios_tab(parent, state):
    """Záložka pre scenárovú analýzu"""
    # === Info panel ===
    info_frame = ttk.LabelFrame(parent, text="Vybraná stratégia", padding=10)
    info_frame.pack(fill='x', padx=10, pady=10)
    
    scenario_info_label = ttk.Label(info_frame, text="Najprv nájdite hedge alebo spustite optimalizáciu")
    scenario_info_label.pack(fill='x')
    
    # Ulož referenciu do state
    state.scenario_info_label = scenario_info_label
    
    # Tlačidlá
    btn_frame = ttk.Frame(info_frame)
    btn_frame.pack(fill='x', pady=5)
    
    ttk.Button(btn_frame, text="📊 GENEROVAŤ SCENÁRE", 
               command=lambda: generate_scenarios(state)).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="📁 Export", 
               command=lambda: export_scenarios(state)).pack(side='left', padx=5)
    
    # === P/L Matica ===
    matrix_frame = ttk.LabelFrame(parent, text="P/L Matica (Cena × Čas)", padding=10)
    matrix_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    # Treeview pre maticu
    matrix_tree = ttk.Treeview(matrix_frame, show='headings', height=8)
    matrix_tree.pack(fill='both', expand=True)
    
    # Ulož referenciu do state
    state.matrix_tree = matrix_tree
    
    # === Legendy ===
    legend_frame = ttk.Frame(parent)
    legend_frame.pack(fill='x', padx=10, pady=5)
    
    # Farebné legendy
    ttk.Label(legend_frame, text="Legenda:", font=('Arial', 9, 'bold')).pack(side='left', padx=5)
    
    profit_label = tk.Label(legend_frame, text="  PROFIT  ", bg='#90EE90')
    profit_label.pack(side='left', padx=5)
    
    neutral_label = tk.Label(legend_frame, text="  NEUTRAL  ", bg='#FFFACD')
    neutral_label.pack(side='left', padx=5)
    
    loss_label = tk.Label(legend_frame, text="  LOSS  ", bg='#FFB6C1')
    loss_label.pack(side='left', padx=5)
    
    # === Scenáre text ===
    scenarios_text_frame = ttk.LabelFrame(parent, text="Detaily scenárov", padding=10)
    scenarios_text_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    scenarios_text = scrolledtext.ScrolledText(scenarios_text_frame, height=10, font=('Courier', 9))
    scenarios_text.pack(fill='both', expand=True)
    
    # Ulož referenciu do state
    state.scenarios_text = scenarios_text

