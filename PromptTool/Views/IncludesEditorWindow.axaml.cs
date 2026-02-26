using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace PromptTool.Views;

public partial class IncludesEditorWindow : Window
{
    private readonly ObservableCollection<string> _items = new();
    private readonly Func<IReadOnlyList<string>> _getWildcardNames;
    private readonly Func<string, IReadOnlyList<string>> _getWildcardValues;

    public IncludesEditorWindow()
    {
        InitializeComponent();
        IncludesList.ItemsSource = _items;
        _getWildcardNames = () => Array.Empty<string>();
        _getWildcardValues = _ => Array.Empty<string>();
    }

    public IncludesEditorWindow(
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues)
    {
        InitializeComponent();
        IncludesList.ItemsSource = _items;
        _getWildcardNames = getWildcardNames;
        _getWildcardValues = getWildcardValues;
    }

    public IncludesEditorWindow(
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        IReadOnlyList<string> initial)
        : this(getWildcardNames, getWildcardValues)
    {
        foreach (var item in initial ?? Array.Empty<string>())
        {
            _items.Add(item);
        }
    }

    public static async Task<IReadOnlyList<string>?> ShowAsync(
        Window owner,
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        IReadOnlyList<string> initial)
    {
        var dlg = new IncludesEditorWindow(getWildcardNames, getWildcardValues, initial);
        return await dlg.ShowDialog<IReadOnlyList<string>?>(owner);
    }

    private async void OnAddClicked(object? sender, RoutedEventArgs e)
    {
        var selection = await IncludesPickerDialog.ShowAsync(
            this,
            _getWildcardNames(),
            _getWildcardValues,
            _items.ToList());
        if (selection == null) return;
        _items.Clear();
        foreach (var item in selection)
        {
            _items.Add(item);
        }
    }

    private void OnRemoveClicked(object? sender, RoutedEventArgs e)
    {
        if (IncludesList.SelectedItem is not string item) return;
        _items.Remove(item);
    }

    private void OnMoveUpClicked(object? sender, RoutedEventArgs e)
    {
        if (IncludesList.SelectedItem is not string item) return;
        var index = _items.IndexOf(item);
        if (index <= 0) return;
        _items.Move(index, index - 1);
    }

    private void OnMoveDownClicked(object? sender, RoutedEventArgs e)
    {
        if (IncludesList.SelectedItem is not string item) return;
        var index = _items.IndexOf(item);
        if (index < 0 || index >= _items.Count - 1) return;
        _items.Move(index, index + 1);
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        Close(_items.ToList());
    }

    private void OnCancel(object? sender, RoutedEventArgs e)
    {
        Close(null);
    }
}
