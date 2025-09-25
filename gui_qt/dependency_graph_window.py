"""A Qt window for displaying the wildcard dependency graph visually."""

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from typing import Optional, TYPE_CHECKING, Dict, Any, List

from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QWidget, QHBoxLayout, QApplication
from PySide6.QtCore import Qt, Slot

if TYPE_CHECKING:
    from .wildcard_manager import WildcardManagerWindow
    from core.prompt_processor import PromptProcessor
    from .gui_app import GUIApp

class MplCanvas(FigureCanvas):
    """A custom Matplotlib canvas widget for Qt."""
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()

class DependencyGraphWindow(QDialog):
    """A window to display the wildcard dependency graph visually."""
    def __init__(self, parent: 'WildcardManagerWindow', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.manager_window = parent
        self.processor = processor
        self.graph_data = self.processor.get_wildcard_dependency_graph()
        self.G = nx.DiGraph()
        self.current_focus_node: Optional[str] = None
        self.node_positions = None

        self.setWindowTitle("Wildcard Dependency Graph")
        self.resize(1000, 800)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception: pass

        self._create_widgets()
        self._build_and_draw_graph()

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        # Top bar for controls
        top_bar_layout = QHBoxLayout()
        self.back_button = QPushButton("< Back to Full Graph")
        self.back_button.clicked.connect(self._show_full_graph)
        self.back_button.hide() # Hidden by default
        top_bar_layout.addWidget(self.back_button)
        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)

        # Matplotlib canvas
        self.canvas = MplCanvas(self, width=10, height=8)
        main_layout.addWidget(self.canvas)

        # Bind double-click event
        self.canvas.mpl_connect('button_press_event', self._on_canvas_click)

    @Slot()
    def _show_full_graph(self):
        """Resets the view to the full dependency graph."""
        self.current_focus_node = None
        self.back_button.hide()
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
        self.canvas.axes.clear()
        self.canvas.axes.set_facecolor(bg_color)
        self.canvas.fig.set_facecolor(bg_color)

        if not graph_to_draw.nodes():
            self.canvas.axes.text(0.5, 0.5, "No wildcards with dependencies found.", ha='center', va='center', color=font_color)
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
        nx.draw_networkx_nodes(graph_to_draw, pos_to_draw, ax=self.canvas.axes, nodelist=list(node_colors.keys()), node_color=list(node_colors.values()), node_size=list(node_sizes.values()))
        nx.draw_networkx_edges(graph_to_draw, pos_to_draw, ax=self.canvas.axes, edge_color=edge_color, arrowstyle='->', arrowsize=20, node_size=list(node_sizes.values()), connectionstyle='arc3,rad=0.1')
        nx.draw_networkx_labels(graph_to_draw, pos_to_draw, ax=self.canvas.axes, font_size=8, font_color=font_color)

        self.canvas.axes.set_title("Wildcard Dependencies", color=font_color)
        self.canvas.axes.axis('off')
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
            self.canvas.axes.legend(handles=legend_handles, loc='lower right', facecolor=bg_color, edgecolor=edge_color, labelcolor=font_color, fontsize='small')
            self.canvas.axes.text(0.01, 0.01, "Node size indicates how many other wildcards use it. Double-click a node to focus.", transform=self.canvas.axes.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        else:
            self.canvas.axes.text(0.01, 0.01, f"Showing neighbors of '{self.current_focus_node}'. Double-click a node to focus on it, or the central node to open it.", transform=self.canvas.axes.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        
        self.canvas.fig.tight_layout()

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
                    self.back_button.show()
                    self._build_and_draw_graph()