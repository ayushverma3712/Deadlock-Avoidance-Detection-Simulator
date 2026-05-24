import matplotlib
matplotlib.use('Agg')

from flask import Flask, request, jsonify, render_template, send_from_directory
import matplotlib.pyplot as plt
import networkx as nx
import os
from CORE.system import System
from CORE.rag import WFG

app = Flask(__name__)
STATIC_FOLDER = os.path.join(os.path.dirname(__file__), 'Static')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check_deadlock():
    try:
        data = request.get_json()
        resource_totals = data['resource_totals']
        allocations = data['allocation']
        max_needs = data['maximum']
        terminated_processes = set(data.get('terminated_processes', []))

        # Validate allocation feasibility before system construction
        allocated_sums = [0] * len(resource_totals)
        for alloc in allocations:
            for r, units in enumerate(alloc):
                allocated_sums[r] += units

        for r, total in enumerate(resource_totals):
            if allocated_sums[r] > total:
                return jsonify({
                    "status": "error",
                    "message": f"Invalid allocation: requested {allocated_sums[r]} units for R{r}, but only {total} available."
                })

        # Build system safely
        system = System(resource_totals)
        for pid, (max_need, alloc) in enumerate(zip(max_needs, allocations)):
            if pid in terminated_processes:
                continue
            system.add_process(pid, max_need, alloc)

        # Check safety
        is_safe, safe_seq = system.is_safe(list(terminated_processes))
        for p in system.processes:
            if p.pid in terminated_processes:
                continue
            p.status = "ready" if p.pid in safe_seq else "waiting"

        deadlocked = []
        termination_recommendation = None
        termination_pid = None

        if not is_safe:
            wfg = WFG(system)
            wfg.build_graph()
            deadlocked = wfg.detect_deadlock()
            termination_pid = wfg.recommend_process_to_terminate()

            if termination_pid is not None and 0 <= termination_pid < len(system.processes):
                held_resources = system.processes[termination_pid].allocation
                termination_recommendation = (
                    f"Terminate P{termination_pid} to break circular wait. "
                    f"This process holds resources: {held_resources}"
                )
            else:
                termination_recommendation = (
                    "No further termination recommendation available. "
                    "Deadlock may persist or system is unrecoverable."
                )

        # Draw Resource Allocation Graph
        G = nx.DiGraph()

        # Add resource and process nodes
        for res in system.resources:
            G.add_node(f"R{res.rid}", shape='s')
        for p in system.processes:
            if p.pid not in terminated_processes:
                G.add_node(f"P{p.pid}", shape='o')

        # Allocation edges (R -> P)
        for p in system.processes:
            if p.pid in terminated_processes:
                continue
            for r, qty in enumerate(p.allocation):
                if qty > 0:
                    G.add_edge(
                        f"R{r}", f"P{p.pid}",
                        type='alloc',
                        label='alloc',
                        color=('darkred' if p.pid in deadlocked else 'green')
                    )

        # Request edges (P -> R)
        for p in system.processes:
            if p.pid in terminated_processes or p.status != "waiting":
                continue
            for r, need in enumerate(p.need):
                if need > system.available[r]:
                    G.add_edge(
                        f"P{p.pid}", f"R{r}",
                        type='req',
                        label='req',
                        color=('darkred' if p.pid in deadlocked else 'blue')
                    )

        # Node colors
        node_colors = []
        for node in G.nodes():
            if node.startswith('R'):
                node_colors.append('lightblue')
            else:
                pid = int(node[1:])
                if not is_safe and pid in deadlocked:
                    node_colors.append('red' if pid == termination_pid else 'orange')
                else:
                    node_colors.append('lightgreen')

        pos = nx.spring_layout(G)

        plt.figure(figsize=(10, 5))
        nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=2000)
        nx.draw_networkx_labels(G, pos, font_size=10)

        edge_colors = [d['color'] for _, _, d in G.edges(data=True)]
        nx.draw_networkx_edges(G, pos, edge_color=edge_colors, arrows=True, arrowstyle='-|>', arrowsize=20, width=2)
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=9, font_color='black', label_pos=0.5)

        plt.title("Safe State" if is_safe else "Deadlock Detected")
        plt.axis('off')

        graph_path = os.path.join(STATIC_FOLDER, "graph.png")
        plt.savefig(graph_path)
        plt.close()

        return jsonify({
            "status": "safe" if is_safe else "deadlock",
            "safe_sequence": [f"P{pid}" for pid in safe_seq] if is_safe else [],
            "message": "✅ System is in safe state" if is_safe else "⚠️ Deadlock detected",
            "deadlocked_processes": [f"P{pid}" for pid in deadlocked],
            "termination_recommendation": termination_recommendation,
            "graph_url": "/graph"
        })

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        })

@app.route('/graph')
def get_graph():
    return send_from_directory(STATIC_FOLDER, "graph.png")

if __name__ == '__main__':
    app.run(debug=True)
