"""A window for displaying statistics about model usage based on history."""

import tkinter as tk
import queue
import threading
from tkinter import ttk
from typing import TYPE_CHECKING, Dict, Any, Optional
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
        self.all_invokeai_models: Optional[List[str]] = None
        self.stats_queue = queue.Queue()
        self.after_id: Optional[str] = None
        self.chart_type_var = tk.StringVar(value="count")

        self._create_widgets()
        self._start_loading_stats()
        self.smart_geometry(min_width=800, min_height=600)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        """Ensure the matplotlib figure is closed to free memory."""
        if hasattr(self, 'fig'):
            plt.close(self.fig)
        self.destroy()

        if self.after_id:
            self.after_cancel(self.after_id)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # --- Statistics Table Tab ---
        table_tab = ttk.Frame(notebook, padding=10)
        notebook.add(table_tab, text="Statistics Table")

        tree_frame = ttk.Frame(table_tab)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('model_name', 'count', 'avg_duration', 'min_duration', 'max_duration')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        self.tree.heading('model_name', text='Model Name', command=lambda: self._sort_treeview_column('model_name', False))
        self.tree.heading('count', text='Generation Count', command=lambda: self._sort_treeview_column('count', False))
        self.tree.heading('avg_duration', text='Avg Time (s)', command=lambda: self._sort_treeview_column('avg_duration', False))
        self.tree.heading('min_duration', text='Min Time (s)', command=lambda: self._sort_treeview_column('min_duration', False))
        self.tree.heading('max_duration', text='Max Time (s)', command=lambda: self._sort_treeview_column('max_duration', False))

        self.tree.column('model_name', width=300)
        self.tree.column('count', width=100, anchor='center')
        self.tree.column('avg_duration', width=100, anchor='center')
        self.tree.column('min_duration', width=100, anchor='center')
        self.tree.column('max_duration', width=100, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- Chart Tab ---
        chart_tab = ttk.Frame(notebook, padding=10)
        notebook.add(chart_tab, text="Charts")

        chart_controls = ttk.Frame(chart_tab)
        chart_controls.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(chart_controls, text="Chart:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Radiobutton(chart_controls, text="Usage Count", variable=self.chart_type_var, value="count", command=self._draw_chart).pack(side=tk.LEFT)
        ttk.Radiobutton(chart_controls, text="Average Time", variable=self.chart_type_var, value="avg_duration", command=self._draw_chart).pack(side=tk.LEFT, padx=10)

        self.fig = plt.Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_tab)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # --- Bottom Controls ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _start_loading_stats(self):
        """Starts fetching stats in a background thread to keep the UI responsive."""
        self.tree.insert('', tk.END, values=("Loading history data...", "", "", "", ""), tags=('disabled',))
        self.tree.tag_configure('disabled', foreground='gray')

        def task():
            try:
                # Fetch stats from history
                stats = self.processor.get_model_stats()
                # Fetch all available models from InvokeAI if connected
                if self.processor.is_invokeai_connected():
                    all_models_data = self.processor.get_invokeai_models()
                    self.all_invokeai_models = [m['name'] for m in all_models_data]
                self.stats_queue.put({'success': True, 'stats': stats})
            except Exception as e:
                self.stats_queue.put({'success': False, 'error': str(e)})

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        self.after_id = self.after(100, self._check_stats_queue)

    def _check_stats_queue(self):
        """Fetches stats from the processor and populates the tree."""
        for i in self.tree.get_children():
            self.tree.delete(i)

        try:
            result = self.stats_queue.get_nowait()
            if result['success']:
                self.stats = result['stats']

                # --- NEW: Merge with all available models ---
                if self.all_invokeai_models:
                    for model_name in self.all_invokeai_models:
                        if model_name not in self.stats:
                            # Add models with 0 usage
                            self.stats[model_name] = {'count': 0, 'avg_duration': 0.0, 'min_duration': 0.0, 'max_duration': 0.0}
                # --- End of new logic ---

                if not self.stats:
                    self.tree.insert('', tk.END, values=("No image generation history found.", "", "", "", ""), tags=('disabled',))
                    self.tree.tag_configure('disabled', foreground='gray')
                    for col in self.tree['columns']: self.tree.heading(col, command=lambda: None)
                else:
                    self.tree.heading('model_name', command=lambda: self._sort_treeview_column('model_name', False))
                    self.tree.heading('count', command=lambda: self._sort_treeview_column('count', False))
                    self.tree.heading('avg_duration', command=lambda: self._sort_treeview_column('avg_duration', False))
                    self.tree.heading('min_duration', command=lambda: self._sort_treeview_column('min_duration', False))
                    self.tree.heading('max_duration', command=lambda: self._sort_treeview_column('max_duration', False))
                    sorted_stats = sorted(self.stats.items(), key=lambda item: item[1]['count'], reverse=True)
                    for model_name, data in sorted_stats:
                        values = (model_name, data['count'], f"{data['avg_duration']:.2f}" if data['avg_duration'] > 0 else "N/A", f"{data['min_duration']:.2f}" if data['min_duration'] > 0 else "N/A", f"{data['max_duration']:.2f}" if data['max_duration'] > 0 else "N/A")
                        self.tree.insert('', tk.END, values=values)
                self._draw_chart()
            else:
                self.tree.insert('', tk.END, values=(f"Error: {result['error']}", "", "", "", ""))
        except queue.Empty:
            self.after_id = self.after(100, self._check_stats_queue)

    def _sort_treeview_column(self, col: str, reverse: bool):
        """Sorts the treeview by a given column."""
        data_list = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        
        # Attempt to sort numerically, otherwise sort as string
        try:
            data_list.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            data_list.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(data_list):
            self.tree.move(k, '', index)

        self.tree.heading(col, command=lambda: self._sort_treeview_column(col, not reverse))

    def _draw_chart(self):
        """Draws the bar chart based on the selected data type."""
        self.ax.clear()
        is_dark = self.parent_app.theme_manager.current_theme == "dark"
        bg_color = '#2e2e2e' if is_dark else '#f0f0f0'
        font_color = 'white' if is_dark else 'black'
        bar_color = '#4a90e2' if is_dark else '#3399ff'

        self.fig.patch.set_facecolor(bg_color)
        self.ax.set_facecolor(bg_color)

        chart_key = self.chart_type_var.get()
        chart_data = {model: data[chart_key] for model, data in self.stats.items() if data[chart_key] > 0}

        if not chart_data:
            self.ax.text(0.5, 0.5, "No data to display.", color=font_color, ha='center', va='center')
            self.canvas.draw()
            return

        sorted_data = sorted(chart_data.items(), key=lambda item: item[1], reverse=False)
        models = [item[0] for item in sorted_data]
        values = [item[1] for item in sorted_data]

        bars = self.ax.barh(models, values, color=bar_color)
        self.ax.tick_params(axis='y', colors=font_color)
        self.ax.tick_params(axis='x', colors=font_color)

        title = "Image Generation Count per Model" if chart_key == 'count' else "Average Generation Time per Model (s)"
        self.ax.set_title(title, color=font_color)
        
        # Add value labels to the bars
        for bar in bars:
            width = bar.get_width()
            label_text = f'{width:.2f}' if isinstance(width, float) and chart_key != 'count' else f'{int(width)}'
            self.ax.text(width + (self.ax.get_xlim()[1] * 0.01), bar.get_y() + bar.get_height()/2, label_text, va='center', color=font_color)
        
        # Adjust subplot to give more space for long model names on the y-axis, preventing the UserWarning.
        self.fig.subplots_adjust(left=0.35, right=0.95, top=0.9, bottom=0.1)
        self.canvas.draw()