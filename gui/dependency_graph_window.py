"""A window for displaying the wildcard dependency graph visually."""

import tkinter as tk
from tkinter import ttk
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from typing import Optional, TYPE_CHECKING

from . import custom_dialogs

if TYPE_CHECKING:
    from .wildcard_manager import WildcardManagerWindow
    from core.prompt_processor import PromptProcessor

class DependencyGraphWindow(custom_dialogs._CustomDialog):
    """A window to display the wildcard dependency graph visually."""
    def __init__(self, parent: 'WildcardManagerWindow', processor: 'PromptProcessor'):
        super().__init__(parent, "Wildcard Dependency Graph")
        self.manager_window = parent
        self.processor = processor
        self.graph_data = self.processor.get_wildcard_dependency_graph()
        self.G = nx.DiGraph()
        self.current_focus_node: Optional[str] = None
        self.node_positions = None
        self.ax = None
        self.canvas = None
        self.fig = None
        self.back_button: Optional[ttk.Button] = None

        self._create_widgets()
        self._build_and_draw_graph()

        self.geometry("1000x800")
        self._center_window()
        self.wait_window(self)

    def destroy(self):
        """Override destroy to also close the matplotlib figure."""
        if self.fig:
            plt.close(self.fig)
        super().destroy()

    def _create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top bar for controls
        top_bar = ttk.Frame(main_frame)
        top_bar.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.back_button = ttk.Button(top_bar, text="< Back to Full Graph", command=self._show_full_graph)
        # The back button is packed/unpacked dynamically

        # Matplotlib canvas
        self.fig = plt.figure(figsize=(10, 8))
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=main_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Matplotlib toolbar
        toolbar = NavigationToolbar2Tk(self.canvas, main_frame)
        toolbar.update()

        # Bind double-click event
        self.canvas.mpl_connect('button_press_event', self._on_canvas_click)

    def _show_full_graph(self):
        """Resets the view to the full dependency graph."""
        self.current_focus_node = None
        if self.back_button:
            self.back_button.pack_forget()
        self._build_and_draw_graph()

    def _build_and_draw_graph(self):
        # Build the full graph G if it's not already built
        if not self.G.nodes():
            for node, data in self.graph_data.items():
                self.G.add_node(node)
                for dep in data.get('dependencies', []):
                    self.G.add_edge(node, dep)

        # Determine which graph to draw
        graph_to_draw = self.G
        if self.current_focus_node:
            neighbors = list(nx.all_neighbors(self.G, self.current_focus_node))
            nodes_for_subgraph = [self.current_focus_node] + neighbors
            graph_to_draw = self.G.subgraph(nodes_for_subgraph)
        
        is_dark = self.manager_window.parent_app.theme_manager.current_theme == "dark"
        bg_color = '#2e2e2e' if is_dark else '#f0f0f0'
        font_color = '#ffffff' if is_dark else '#000000'
        self.ax.clear()
        self.ax.set_facecolor(bg_color)
        self.ax.figure.set_facecolor(bg_color)

        if not graph_to_draw.nodes():
            self.ax.text(0.5, 0.5, "No wildcards with dependencies found.", ha='center', va='center', color=font_color)
            self.canvas.draw()
            return

        # Use a layout that spreads nodes out nicely
        if self.node_positions is None:
            try:
                self.node_positions = nx.spring_layout(self.G, k=0.9, iterations=75, seed=42)
            except Exception:
                self.node_positions = nx.kamada_kawai_layout(self.G)
        
        pos_to_draw = {node: self.node_positions[node] for node in graph_to_draw.nodes()}

        # --- Drawing ---
        full_in_degrees = dict(self.G.in_degree())
        node_colors, node_sizes = self._get_node_styles(graph_to_draw, full_in_degrees)

        edge_color = '#555555' if is_dark else '#999999'

        # Draw the graph
        nx.draw_networkx_nodes(graph_to_draw, pos_to_draw, ax=self.ax, nodelist=list(node_colors.keys()), node_color=list(node_colors.values()), node_size=list(node_sizes.values()))
        nx.draw_networkx_edges(graph_to_draw, pos_to_draw, ax=self.ax, edge_color=edge_color, arrowstyle='->', arrowsize=20, node_size=list(node_sizes.values()), connectionstyle='arc3,rad=0.1')
        nx.draw_networkx_labels(graph_to_draw, pos_to_draw, ax=self.ax, font_size=8, font_color=font_color)

        self.ax.set_title("Wildcard Dependencies", color=font_color)
        self.ax.axis('off')
        self._draw_legend_and_text(font_color, edge_color, bg_color)
        self.canvas.draw_idle()

    def _get_node_styles(self, graph_to_draw, full_in_degrees):
        """Calculates colors and sizes for the nodes in the graph to be drawn."""
        node_colors, node_sizes = {}, {}
        is_dark = self.manager_window.parent_app.theme_manager.current_theme == "dark"
        
        # Define colors
        root_color, leaf_color = '#2E8B57', '#4682B4'
        intermediate_color = '#4a5e73' if is_dark else '#add8e6'
        isolated_color, focus_color = '#808080', '#FFD700'

        for node in graph_to_draw.nodes():
            node_sizes[node] = 1500 + full_in_degrees.get(node, 0) * 400
            
            if node == self.current_focus_node:
                node_colors[node] = focus_color
            elif self.G.in_degree(node) == 0 and self.G.out_degree(node) > 0:
                node_colors[node] = root_color
            elif self.G.out_degree(node) == 0 and self.G.in_degree(node) > 0:
                node_colors[node] = leaf_color
            elif self.G.in_degree(node) == 0 and self.G.out_degree(node) == 0:
                node_colors[node] = isolated_color
            else:
                node_colors[node] = intermediate_color
        
        return node_colors, node_sizes

    def _draw_legend_and_text(self, font_color, edge_color, bg_color):
        """Draws the legend and instructional text on the canvas."""
        if not self.current_focus_node:
            legend_handles = [
                mpatches.Patch(color='#2E8B57', label='Root (Starts a chain)'),
                mpatches.Patch(color='#4682B4', label='Leaf (End of a chain)'),
                mpatches.Patch(color='#4a5e73' if self.manager_window.parent_app.theme_manager.current_theme == "dark" else '#add8e6', label='Intermediate'),
                mpatches.Patch(color='#808080', label='Isolated (No links)')
            ]
            self.ax.legend(handles=legend_handles, loc='lower right', facecolor=bg_color, edgecolor=edge_color, labelcolor=font_color, fontsize='small')
            self.ax.text(0.01, 0.01, "Node size indicates how many other wildcards use it. Double-click a node to focus.", transform=self.ax.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        else:
            self.ax.text(0.01, 0.01, f"Showing neighbors of '{self.current_focus_node}'. Double-click a node to focus on it, or the central node to open it.", transform=self.ax.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        
        plt.tight_layout()

    def _on_canvas_click(self, event):
        if event.dblclick and self.node_positions and event.xdata is not None and event.ydata is not None:
            # Find the node closest to the click
            min_dist = float('inf')
            closest_node = None
            for node, pos in self.node_positions.items():
                dist_sq = (pos[0] - event.xdata)**2 + (pos[1] - event.ydata)**2
                if dist_sq < min_dist:
                    min_dist = dist_sq
                    closest_node = node

            if closest_node and min_dist < 0.01: # Threshold to confirm click was on a node
                if self.current_focus_node == closest_node:
                    self.manager_window.select_and_load_file(f"{closest_node}.json")
                    self.manager_window.lift()
                    self.destroy()
                else:
                    self.current_focus_node = closest_node
                    if self.back_button: self.back_button.pack(side=tk.LEFT, anchor='w')
                    self._build_and_draw_graph()