using System;

namespace PromptTool.Core.Clients.InvokeAI;

public static class ModelResolutionHelper
{
    public static bool MatchesIdentity(InvokeAIModel candidate, string? nameOrKey, string? key, string? hash)
    {
        if (!string.IsNullOrWhiteSpace(nameOrKey) &&
            (string.Equals(candidate.Name, nameOrKey, StringComparison.OrdinalIgnoreCase) ||
             string.Equals(candidate.Key, nameOrKey, StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }

        if (!string.IsNullOrWhiteSpace(key) &&
            (string.Equals(candidate.Key, key, StringComparison.OrdinalIgnoreCase) ||
             string.Equals(candidate.Name, key, StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }

        if (!string.IsNullOrWhiteSpace(hash) &&
            string.Equals(candidate.Hash, hash, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return false;
    }

    public static bool LooksLikeGuid(string? value)
        => !string.IsNullOrWhiteSpace(value) && Guid.TryParse(value, out _);

    public static int ScoreCandidate(InvokeAIModel candidate, string? originalName, string? preferredBase)
    {
        var score = 0;
        if (!string.IsNullOrWhiteSpace(preferredBase) &&
            string.Equals(candidate.Base, preferredBase, StringComparison.OrdinalIgnoreCase))
        {
            score += 100;
        }

        if (!string.IsNullOrWhiteSpace(originalName) && !LooksLikeGuid(originalName))
        {
            if (string.Equals(candidate.Name, originalName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(candidate.Key, originalName, StringComparison.OrdinalIgnoreCase))
            {
                score += 1000;
            }
            else
            {
                if (candidate.Name.Contains(originalName, StringComparison.OrdinalIgnoreCase))
                {
                    score += 120;
                }

                if (originalName.Contains(candidate.Name, StringComparison.OrdinalIgnoreCase))
                {
                    score += 90;
                }
            }
        }

        return score;
    }
}
