"""A window for displaying statistics about model usage based on history."""

import tkinter as tk
import queue
import threading
from tkinter import ttk
from typing import TYPE_CHECKING, Dict, Optional
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .common import SmartWindowMixin

if TYPE_CHECKING:
    from .gui_app import GUIApp
    from core.prompt_processor import PromptProcessor

class ModelUsageViewer(tk.Toplevel, SmartWindowMixin):
    """A window to display statistics about model usage."""
    def __init__(self, parent: 'GUIApp', processor: 'PromptProcessor'):
        super().__init__(parent)
        self.title("Model Usage Statistics")
        self.processor = processor
        self.parent_app = parent
        self.stats: Dict[str, Dict[str, float]] = {}
        self.lora_stats: Dict[str, int] = {}
        self.all_invokeai_models: Optional[List[str]] = None
        self.stats_queue = queue.Queue()
        self.after_id: Optional[str] = None
        self.chart_type_var = tk.StringVar(value="count")
        self.lora_chart_type_var = tk.StringVar(value="count")

        self._create_widgets()
        self._start_loading_stats()
        self.smart_geometry(min_width=800, min_height=600)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        """Ensure the matplotlib figure is closed to free memory."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None

        if hasattr(self, 'fig'):
            plt.close(self.fig)
        if hasattr(self, 'lora_fig'):
            plt.close(self.lora_fig)

        self.destroy()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # --- Statistics Table Tab ---
        model_table_tab = ttk.Frame(notebook, padding=10)
        notebook.add(model_table_tab, text="Model Statistics")

        tree_frame = ttk.Frame(model_table_tab)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('model_name', 'count', 'avg_duration', 'total_duration', 'min_duration', 'max_duration')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        self.tree.heading('model_name', text='Model Name', command=lambda: self._sort_treeview_column('model_name', False))
        self.tree.heading('count', text='Generation Count', command=lambda: self._sort_treeview_column('count', False))
        self.tree.heading('avg_duration', text='Avg Time (s)', command=lambda: self._sort_treeview_column('avg_duration', False))
        self.tree.heading('total_duration', text='Total Time (m)', command=lambda: self._sort_treeview_column('total_duration', False))
        self.tree.heading('min_duration', text='Min Time (s)', command=lambda: self._sort_treeview_column('min_duration', False))
        self.tree.heading('max_duration', text='Max Time (s)', command=lambda: self._sort_treeview_column('max_duration', False))

        self.tree.column('model_name', width=300)
        self.tree.column('count', width=100, anchor='center')
        self.tree.column('avg_duration', width=100, anchor='center')
        self.tree.column('total_duration', width=100, anchor='center')
        self.tree.column('min_duration', width=100, anchor='center')
        self.tree.column('max_duration', width=100, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- Model Chart Tab ---
        model_chart_tab = ttk.Frame(notebook, padding=10)
        notebook.add(model_chart_tab, text="Model Charts")

        chart_controls = ttk.Frame(model_chart_tab)
        chart_controls.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(chart_controls, text="Chart:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Radiobutton(chart_controls, text="Usage Count", variable=self.chart_type_var, value="count", command=self._draw_chart).pack(side=tk.LEFT)
        ttk.Radiobutton(chart_controls, text="Average Time", variable=self.chart_type_var, value="avg_duration", command=self._draw_chart).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(chart_controls, text="Total Time", variable=self.chart_type_var, value="total_duration", command=self._draw_chart).pack(side=tk.LEFT)

        self.fig = plt.Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=model_chart_tab)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # --- LoRA Statistics Tab ---
        lora_tab = ttk.Frame(notebook, padding=10)
        notebook.add(lora_tab, text="LoRA Statistics")

        lora_tree_frame = ttk.Frame(lora_tab)
        lora_tree_frame.pack(fill=tk.BOTH, expand=True)

        lora_columns = ('lora_name', 'count')
        self.lora_tree = ttk.Treeview(lora_tree_frame, columns=lora_columns, show='headings')
        self.lora_tree.heading('lora_name', text='LoRA Name', command=lambda: self._sort_treeview_column('lora_name', False, tree=self.lora_tree))
        self.lora_tree.heading('count', text='Usage Count', command=lambda: self._sort_treeview_column('count', False, tree=self.lora_tree))

        self.lora_tree.column('lora_name', width=400)
        self.lora_tree.column('count', width=100, anchor='center')

        lora_scrollbar = ttk.Scrollbar(lora_tree_frame, orient=tk.VERTICAL, command=self.lora_tree.yview)
        self.lora_tree.configure(yscrollcommand=lora_scrollbar.set)
        lora_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lora_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- LoRA Chart Tab ---
        lora_chart_tab = ttk.Frame(notebook, padding=10)
        notebook.add(lora_chart_tab, text="LoRA Chart")

        self.lora_fig = plt.Figure(figsize=(5, 4), dpi=100)
        self.lora_ax = self.lora_fig.add_subplot(111)
        self.lora_canvas = FigureCanvasTkAgg(self.lora_fig, master=lora_chart_tab)
        self.lora_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # --- Bottom Controls ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _start_loading_stats(self):
        """Starts fetching stats in a background thread to keep the UI responsive."""
        self.tree.insert('', tk.END, values=("Loading history data...", "", "", "", "", ""), tags=('disabled',))
        self.tree.tag_configure('disabled', foreground='gray')
        self.lora_tree.insert('', tk.END, values=("Loading history data...", ""), tags=('disabled',))
        self.lora_tree.tag_configure('disabled', foreground='gray')

        def task():
            try:
                # Fetch stats from history
                stats = self.processor.get_model_stats()
                lora_stats = self.processor.get_lora_stats()
                # Fetch all available models from InvokeAI if connected
                if self.processor.is_invokeai_connected():
                    all_models_data = self.processor.get_invokeai_models()
                    self.all_invokeai_models = [m['name'] for m in all_models_data]
                self.stats_queue.put({'success': True, 'stats': stats, 'lora_stats': lora_stats})
            except Exception as e:
                self.stats_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_stats_queue)

    def _check_stats_queue(self):
        """Fetches stats from the processor and populates the tree."""
        for i in self.tree.get_children():
            self.tree.delete(i)
        for i in self.lora_tree.get_children():
            self.lora_tree.delete(i)

        try:
            result = self.stats_queue.get_nowait()
            if result['success']:
                self.stats = result['stats']

                # --- NEW: Merge with all available models ---
                if self.all_invokeai_models:
                    for model_name in self.all_invokeai_models:
                        if model_name not in self.stats:
                            # Add models with 0 usage
                            self.stats[model_name] = {'count': 0, 'avg_duration': 0.0, 'total_duration': 0.0, 'min_duration': 0.0, 'max_duration': 0.0}
                # --- End of new logic ---

                if not self.stats:
                    self.tree.insert('', tk.END, values=("No image generation history found.", "", "", "", "", ""), tags=('disabled',))
                    self.tree.tag_configure('disabled', foreground='gray')
                    for col in self.tree['columns']: self.tree.heading(col, command=lambda: None)
                else:
                    self.tree.heading('model_name', command=lambda: self._sort_treeview_column('model_name', False))
                    self.tree.heading('count', command=lambda: self._sort_treeview_column('count', False))
                    self.tree.heading('avg_duration', command=lambda: self._sort_treeview_column('avg_duration', False))
                    self.tree.heading('total_duration', command=lambda: self._sort_treeview_column('total_duration', False))
                    self.tree.heading('min_duration', command=lambda: self._sort_treeview_column('min_duration', False))
                    self.tree.heading('max_duration', command=lambda: self._sort_treeview_column('max_duration', False))
                    sorted_stats = sorted(self.stats.items(), key=lambda item: item[1]['count'], reverse=True)
                    for model_name, data in sorted_stats:
                        total_duration_min = data.get('total_duration', 0) / 60
                        values = (
                            model_name, 
                            data['count'], 
                            f"{data['avg_duration']:.2f}" if data['avg_duration'] > 0 else "N/A", 
                            f"{total_duration_min:.2f}" if total_duration_min > 0 else "N/A",
                            f"{data['min_duration']:.2f}" if data['min_duration'] > 0 else "N/A", 
                            f"{data['max_duration']:.2f}" if data['max_duration'] > 0 else "N/A"
                        )
                        self.tree.insert('', tk.END, values=values)
                self._draw_chart()

                # --- Populate LoRA stats ---
                self.lora_stats = result.get('lora_stats', {})
                if not self.lora_stats:
                    self.lora_tree.insert('', tk.END, values=("No LoRA usage found in history.", ""), tags=('disabled',))
                else:
                    sorted_lora_stats = sorted(self.lora_stats.items(), key=lambda item: item[1], reverse=True)
                    for lora_name, count in sorted_lora_stats:
                        self.lora_tree.insert('', tk.END, values=(lora_name, count))
                self._draw_lora_chart()
            else:
                self.tree.insert('', tk.END, values=(f"Error: {result['error']}", "", "", "", "", ""))
                self.lora_tree.insert('', tk.END, values=(f"Error: {result['error']}", ""))
        except queue.Empty:
            self.after_id = self.after(100, self._check_stats_queue)

    def _sort_treeview_column(self, col: str, reverse: bool, tree: Optional[ttk.Treeview] = None):
        """Sorts the treeview by a given column."""
        if tree is None:
            tree = self.tree
        data_list = [(tree.set(k, col), k) for k in tree.get_children('')]
        
        # Attempt to sort numerically, otherwise sort as string
        try:
            data_list.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            data_list.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(data_list):
            tree.move(k, '', index)

        tree.heading(col, command=lambda: self._sort_treeview_column(col, not reverse, tree))

    def _draw_horizontal_bar_chart(self, ax, fig, canvas, data: Dict[str, float], title: str, is_float: bool):
        """A generic function to draw a styled horizontal bar chart."""
        ax.clear()
        is_dark = self.parent_app.theme_manager.current_theme == "dark"
        bg_color = '#2e2e2e' if is_dark else '#f0f0f0'
        font_color = 'white' if is_dark else 'black'

        # --- NEW: Limit data to top N for a clean, fixed-size chart ---
        MAX_ITEMS_TO_SHOW = 20
        all_sorted_items = sorted(data.items(), key=lambda item: item[1], reverse=True)

        if len(all_sorted_items) > MAX_ITEMS_TO_SHOW:
            title += f" (Top {MAX_ITEMS_TO_SHOW})"
        
        # Take the top N items and then sort them ascending for correct barh plotting (largest at top)
        items_to_plot = sorted(all_sorted_items[:MAX_ITEMS_TO_SHOW], key=lambda item: item[1])

        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        if not items_to_plot:
            ax.text(0.5, 0.5, "No data to display.", color=font_color, ha='center', va='center', fontsize=10)
            canvas.draw()
            return

        # Sort data for plotting
        models = [item[0] for item in items_to_plot]
        values = [item[1] for item in items_to_plot]

        # --- Modern Styling ---
        # Use a colormap for the bars. 'viridis_r' goes from purple (low) to yellow (high).
        cmap = plt.cm.get_cmap('viridis_r')
        # Normalize values to the range [0, 1] for the colormap
        norm = plt.Normalize(min(values) if values else 0, max(values) if values else 1)
        bar_colors = cmap(norm(values))

        bars = ax.barh(models, values, color=bar_colors, edgecolor=font_color, linewidth=0.5, alpha=0.9)

        # Remove top and right spines for a cleaner look
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(font_color)
        ax.spines['bottom'].set_color(font_color)

        # Add a subtle grid
        ax.grid(axis='x', color=font_color, linestyle=':', linewidth=0.5, alpha=0.5)
        ax.set_axisbelow(True) # Draw grid behind bars

        ax.tick_params(axis='y', colors=font_color)
        ax.tick_params(axis='x', colors=font_color)
        ax.set_title(title, color=font_color, fontsize=12, pad=15)

        # Add value labels to the bars
        for bar in bars:
            width = bar.get_width()
            label_text = f'{width:.2f}' if is_float else f'{int(width)}'
            ax.text(width + (ax.get_xlim()[1] * 0.01), bar.get_y() + bar.get_height()/2, label_text, va='center', color=font_color, fontsize=8)

        # Use fixed subplot adjustments for a stable layout
        fig.subplots_adjust(left=0.35, right=0.95, top=0.9, bottom=0.1)
        canvas.draw()

    def _draw_chart(self):
        """Draws the bar chart for models based on the selected data type."""
        chart_key = self.chart_type_var.get()
        title_map = {
            "count": "Image Generation Count per Model",
            "avg_duration": "Average Generation Time per Model (s)",
            "total_duration": "Total Generation Time per Model (minutes)"
        }
        title = title_map.get(chart_key, "Model Statistics")

        if chart_key == 'total_duration':
            chart_data = {model: data[chart_key] / 60 for model, data in self.stats.items() if data[chart_key] > 0}
        else:
            chart_data = {model: data[chart_key] for model, data in self.stats.items() if data[chart_key] > 0}

        is_float = chart_key != 'count'
        self._draw_horizontal_bar_chart(self.ax, self.fig, self.canvas, chart_data, title, is_float)

    def _draw_lora_chart(self):
        """Draws the bar chart for LoRA usage."""
        self._draw_horizontal_bar_chart(self.lora_ax, self.lora_fig, self.lora_canvas, self.lora_stats, "LoRA Usage Count", is_float=False)