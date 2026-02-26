using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Controls.Templates;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class RequiresEditorWindow : Window
{
    private readonly ObservableCollection<WildcardManagerViewModel.RequirementRule> _rules = new();
    private readonly Func<IReadOnlyList<string>> _getWildcardNames;
    private readonly Func<string, IReadOnlyList<string>> _getWildcardValues;

    public RequiresEditorWindow()
    {
        InitializeComponent();
        _getWildcardNames = () => Array.Empty<string>();
        _getWildcardValues = _ => Array.Empty<string>();
        RulesList.ItemsSource = _rules;
    }

    public RequiresEditorWindow(
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        IReadOnlyList<WildcardManagerViewModel.RequirementRule> initial)
    {
        InitializeComponent();
        _getWildcardNames = getWildcardNames;
        _getWildcardValues = getWildcardValues;
        RulesList.ItemsSource = _rules;

        foreach (var rule in initial ?? Array.Empty<WildcardManagerViewModel.RequirementRule>())
        {
            _rules.Add(rule);
        }

        RulesList.ItemTemplate = new FuncDataTemplate<WildcardManagerViewModel.RequirementRule>((item, _) =>
        {
            return new TextBlock { Text = FormatRule(item) };
        });
    }

    public static async Task<IReadOnlyList<WildcardManagerViewModel.RequirementRule>?> ShowAsync(
        Window owner,
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        IReadOnlyList<WildcardManagerViewModel.RequirementRule> initial)
    {
        var dlg = new RequiresEditorWindow(getWildcardNames, getWildcardValues, initial);
        return await dlg.ShowDialog<IReadOnlyList<WildcardManagerViewModel.RequirementRule>?>(owner);
    }

    private async void OnAddClicked(object? sender, RoutedEventArgs e)
    {
        var rule = await RequiresRulePickerDialog.ShowAsync(this, _getWildcardNames, _getWildcardValues, null);
        if (rule == null) return;
        _rules.Add(rule);
    }

    private async void OnEditClicked(object? sender, RoutedEventArgs e)
    {
        if (RulesList.SelectedItem is not WildcardManagerViewModel.RequirementRule selected) return;
        var updated = await RequiresRulePickerDialog.ShowAsync(this, _getWildcardNames, _getWildcardValues, selected);
        if (updated == null) return;
        var index = _rules.IndexOf(selected);
        if (index >= 0) _rules[index] = updated;
    }

    private void OnRemoveClicked(object? sender, RoutedEventArgs e)
    {
        if (RulesList.SelectedItem is not WildcardManagerViewModel.RequirementRule selected) return;
        _rules.Remove(selected);
    }

    private void OnMoveUpClicked(object? sender, RoutedEventArgs e)
    {
        if (RulesList.SelectedItem is not WildcardManagerViewModel.RequirementRule selected) return;
        var index = _rules.IndexOf(selected);
        if (index <= 0) return;
        _rules.Move(index, index - 1);
    }

    private void OnMoveDownClicked(object? sender, RoutedEventArgs e)
    {
        if (RulesList.SelectedItem is not WildcardManagerViewModel.RequirementRule selected) return;
        var index = _rules.IndexOf(selected);
        if (index < 0 || index >= _rules.Count - 1) return;
        _rules.Move(index, index + 1);
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        Close(_rules.ToList());
    }

    private void OnCancel(object? sender, RoutedEventArgs e)
    {
        Close(null);
    }

    private static string FormatRule(WildcardManagerViewModel.RequirementRule rule)
    {
        var values = string.Join(", ", rule.Values);
        return rule.Operator == "in"
            ? $"{rule.WildcardName} in [{values}]"
            : $"{rule.WildcardName} = {values}";
    }
}
