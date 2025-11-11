"""A Qt window for displaying the wildcard dependency graph visually."""

import networkx as nx
import matplotlib.patches as mpatches
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QWidget, QHBoxLayout, QApplication,
                               QSizePolicy, QSplitter, QGroupBox, QLabel, QLineEdit)
from PySide6.QtCore import Qt, Slot
from core.config import config
from .custom_widgets import SmoothListWidget

if TYPE_CHECKING:
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
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.parent_app = parent
        self.processor = processor
        self.graph_data = self.processor.get_wildcard_dependency_graph()
        self.template_usage_map = self.processor.get_template_usage_map()
        self.G = nx.DiGraph()
        self.current_focus_node: Optional[str] = None
        self.node_positions = None
        self.selected_node: Optional[str] = None

        self.setWindowTitle("Wildcard Dependency Graph")
        self.resize(1200, 800)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception: pass

        self._create_widgets()
        self._build_and_draw_graph()

    def _create_widgets(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Pane: Graph ---
        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)

        top_bar_layout = QHBoxLayout()
        self.back_button = QPushButton("< Back to Full Graph")
        self.back_button.clicked.connect(self._show_full_graph)
        self.back_button.hide()
        top_bar_layout.addWidget(self.back_button)
        top_bar_layout.addStretch()
        graph_layout.addLayout(top_bar_layout)

        self.canvas = MplCanvas(self, width=10, height=8)
        graph_layout.addWidget(self.canvas)
        self.canvas.mpl_connect('button_press_event', self._on_canvas_click)
        
        splitter.addWidget(graph_container)

        # --- Right Pane: Inspector ---
        self._create_inspector_panel()
        splitter.addWidget(self.inspector_panel)

        splitter.setSizes([800, 400])

    def _create_inspector_panel(self):
        """Creates the inspector panel widget and its contents."""
        self.inspector_panel = QGroupBox("Inspector")
        inspector_layout = QVBoxLayout(self.inspector_panel)

        self.inspector_description = QLabel("Click a node to inspect it.")
        self.inspector_description.setWordWrap(True)
        inspector_layout.addWidget(self.inspector_description)

        # Templates
        templates_group = QGroupBox("Used By Templates")
        templates_layout = QVBoxLayout(templates_group)
        self.templates_list = SmoothListWidget()
        templates_layout.addWidget(self.templates_list)
        inspector_layout.addWidget(templates_group)

        # Dependencies
        dependencies_group = QGroupBox("Dependencies")
        dependencies_layout = QHBoxLayout(dependencies_group)
        
        included_by_group = QGroupBox("Included By")
        included_by_layout = QVBoxLayout(included_by_group)
        self.included_by_list = SmoothListWidget()
        included_by_layout.addWidget(self.included_by_list)
        dependencies_layout.addWidget(included_by_group)

        depends_on_group = QGroupBox("Depends On")
        depends_on_layout = QVBoxLayout(depends_on_group)
        self.depends_on_list = SmoothListWidget()
        depends_on_layout.addWidget(self.depends_on_list)
        dependencies_layout.addWidget(depends_on_group)
        inspector_layout.addWidget(dependencies_group)

        # Choices
        choices_group = QGroupBox("Choices")
        choices_layout = QVBoxLayout(choices_group)
        self.choices_search = QLineEdit()
        self.choices_search.setPlaceholderText("Search choices...")
        self.choices_search.textChanged.connect(self._filter_choices)
        self.choices_list = SmoothListWidget()
        choices_layout.addWidget(self.choices_search)
        choices_layout.addWidget(self.choices_list)
        inspector_layout.addWidget(choices_group)

        self.inspector_panel.setVisible(False)

    @Slot(str)
    def _filter_choices(self, text: str):
        """Filters the choices list based on the search text."""
        for i in range(self.choices_list.count()):
            item = self.choices_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _update_inspector_panel(self, node_name: str):
        """Fetches data for the selected node and populates the inspector panel."""
        self.inspector_panel.setVisible(True)
        self.inspector_panel.setTitle(f"Inspector: {node_name}")

        # Get data
        node_data = self.graph_data.get(node_name, {})
        wildcard_data, _ = self.processor.get_wildcard_data_for_editing(f"{node_name}.json")
        templates = self.template_usage_map.get(node_name, [])
        
        # Populate description
        description = wildcard_data.get('description', 'No description available.')
        self.inspector_description.setText(description)

        # Populate lists
        self.templates_list.clear()
        self.templates_list.addItems(templates)
        
        self.included_by_list.clear()
        self.included_by_list.addItems(node_data.get('dependents', []))

        self.depends_on_list.clear()
        self.depends_on_list.addItems(node_data.get('dependencies', []))

        self.choices_list.clear()
        if wildcard_data and 'choices' in wildcard_data:
            choices = [str(c.get('value') if isinstance(c, dict) else c) for c in wildcard_data['choices']]
            self.choices_list.addItems(choices)
        
        self.choices_search.clear()

    @Slot()
    def _show_full_graph(self):
        """Resets the view to the full dependency graph."""
        self.current_focus_node = None
        self.back_button.hide()
        self._build_and_draw_graph()

    def _build_and_draw_graph(self):
        if not self.G.nodes():
            for node, data in self.graph_data.items():
                self.G.add_node(node)
                for dep in data.get('dependencies', []):
                    self.G.add_edge(node, dep)

        graph_to_draw = self.G
        if self.current_focus_node:
            neighbors = list(nx.all_neighbors(self.G, self.current_focus_node))
            nodes_for_subgraph = [self.current_focus_node] + neighbors
            graph_to_draw = self.G.subgraph(nodes_for_subgraph)
        
        is_dark = config.theme == "dark"
        bg_color = '#2e2e2e' if is_dark else '#f0f0f0'
        font_color = '#ffffff' if is_dark else '#000000'
        self.canvas.axes.clear()
        self.canvas.axes.set_facecolor(bg_color)
        self.canvas.fig.set_facecolor(bg_color)

        if not graph_to_draw.nodes():
            self.canvas.axes.text(0.5, 0.5, "No wildcards with dependencies found.", ha='center', va='center', color=font_color)
            self.canvas.draw()
            return

        if self.node_positions is None:
            try:
                self.node_positions = nx.spring_layout(self.G, k=0.9, iterations=75, seed=42)
            except Exception:
                self.node_positions = nx.kamada_kawai_layout(self.G)
        
        pos_to_draw = {node: self.node_positions[node] for node in graph_to_draw.nodes()}

        full_in_degrees = dict(self.G.in_degree())
        node_colors, node_sizes = self._get_node_styles(graph_to_draw, full_in_degrees)
        edge_color = '#555555' if is_dark else '#999999'

        nx.draw_networkx_nodes(graph_to_draw, pos_to_draw, ax=self.canvas.axes, nodelist=list(node_colors.keys()), node_color=list(node_colors.values()), node_size=list(node_sizes.values()))
        nx.draw_networkx_edges(graph_to_draw, pos_to_draw, ax=self.canvas.axes, edge_color=edge_color, arrowstyle='->', arrowsize=20, node_size=list(node_sizes.values()), connectionstyle='arc3,rad=0.1')
        nx.draw_networkx_labels(graph_to_draw, pos_to_draw, ax=self.canvas.axes, font_size=8, font_color=font_color)

        self.canvas.axes.set_title("Wildcard Dependencies", color=font_color)
        self.canvas.axes.axis('off')
        self._draw_legend_and_text(font_color, edge_color, bg_color)
        self.canvas.draw_idle()

    def _get_node_styles(self, graph_to_draw, full_in_degrees):
        node_colors, node_sizes = {}, {}
        is_dark = config.theme == "dark"
        
        root_color, leaf_color = '#2E8B57', '#4682B4'
        intermediate_color = '#4a5e73' if is_dark else '#add8e6'
        isolated_color, focus_color = '#808080', '#FFD700'
        selected_color = '#FF6347' # Tomato color for selection

        for node in graph_to_draw.nodes():
            node_sizes[node] = 1500 + full_in_degrees.get(node, 0) * 400
            
            if node == self.selected_node:
                node_colors[node] = selected_color
            elif node == self.current_focus_node:
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
        if not self.current_focus_node:
            legend_handles = [
                mpatches.Patch(color='#FF6347', label='Selected'),
                mpatches.Patch(color='#2E8B57', label='Root (Starts a chain)'),
                mpatches.Patch(color='#4682B4', label='Leaf (End of a chain)'),
                mpatches.Patch(color='#4a5e73' if config.theme == "dark" else '#add8e6', label='Intermediate'),
                mpatches.Patch(color='#808080', label='Isolated (No links)')
            ]
            self.canvas.axes.legend(handles=legend_handles, loc='lower right', facecolor=bg_color, edgecolor=edge_color, labelcolor=font_color, fontsize='small')
            self.canvas.axes.text(0.01, 0.01, "Click a node to inspect. Double-click to focus.", transform=self.canvas.axes.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        else:
            self.canvas.axes.text(0.01, 0.01, f"Showing neighbors of '{self.current_focus_node}'. Double-click a node to focus, or the central node to open it.", transform=self.canvas.axes.transAxes, fontsize=7, color=font_color, verticalalignment='bottom')
        
        self.canvas.fig.tight_layout()

    def _on_canvas_click(self, event):
        if event.inaxes != self.canvas.axes or not self.node_positions:
            return

        closest_node, distance = self._get_closest_node(event.xdata, event.ydata)

        if closest_node and distance < 0.01: # Click is on a node
            if event.dblclick:
                if self.current_focus_node == closest_node:
                    # Double-clicking the focused node opens it
                    self.parent_app.open_wildcard_manager_and_select_file(f"{closest_node}.json")
                    self.accept()
                else:
                    # Double-clicking any other node focuses on it
                    self.current_focus_node = closest_node
                    self.selected_node = closest_node
                    self.back_button.show()
                    self._build_and_draw_graph()
                    self._update_inspector_panel(closest_node)
            else: # Single click
                self.selected_node = closest_node
                self._build_and_draw_graph() # Redraw to show selection color
                self._update_inspector_panel(closest_node)
        else: # Click is on the background
            self.selected_node = None
            self.inspector_panel.setVisible(False)
            self._build_and_draw_graph() # Redraw to clear selection

    def _get_closest_node(self, x, y):
        """Finds the node in the current layout closest to the given coordinates."""
        min_dist = float('inf')
        closest_node = None
        # Only consider nodes currently being drawn
        nodes_to_check = self.G.nodes if not self.current_focus_node else self.G.subgraph([self.current_focus_node] + list(nx.all_neighbors(self.G, self.current_focus_node))).nodes
        
        for node in nodes_to_check:
            if node not in self.node_positions: continue
            pos = self.node_positions[node]
            dist_sq = (pos[0] - x)**2 + (pos[1] - y)**2
            if dist_sq < min_dist:
                min_dist = dist_sq
                closest_node = node
        return closest_node, min_dist
