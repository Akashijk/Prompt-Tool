using System.Collections.ObjectModel;
using System.Linq;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public class ModelStatsViewModel
{
    public ObservableCollection<string> Stats { get; } = new();

    public ModelStatsViewModel(HistoryManagerService history)
    {
        var entries = history.GetAllEntries();
        var byModel = entries
            .GroupBy(e => e.InvokeAIModel ?? "(unknown)")
            .Select(g => $"{g.Key}: {g.Count()} generations")
            .OrderByDescending(s => s);

        foreach (var line in byModel)
        {
            Stats.Add(line);
        }
    }
}
