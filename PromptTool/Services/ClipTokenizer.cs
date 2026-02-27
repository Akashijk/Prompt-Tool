using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PromptTool.Services;

public sealed class ClipTokenizer
{
    private const string EndOfWord = "</w>";
    private static readonly Regex TokenRegex = new(
        @"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+",
        RegexOptions.Compiled);
    private static readonly Dictionary<byte, string> ByteEncoder = BuildByteEncoder();

    private readonly Dictionary<string, int> _encoder;
    private readonly Dictionary<(string, string), int> _bpeRanks;
    private readonly Dictionary<string, string> _cache = new(StringComparer.Ordinal);
    private readonly int _startToken;
    private readonly int _endToken;

    public ClipTokenizer(string vocabPath, string mergesPath)
    {
        _encoder = LoadVocab(vocabPath);
        _bpeRanks = LoadBpeRanks(mergesPath);
        _startToken = _encoder.TryGetValue("<|startoftext|>", out var start) ? start : 49406;
        _endToken = _encoder.TryGetValue("<|endoftext|>", out var end) ? end : 49407;
    }

    public (long[] InputIds, long[] AttentionMask) Encode(string text, int maxLength)
    {
        var tokens = Tokenize(text);
        var inputIds = new long[maxLength];
        var mask = new long[maxLength];
        var index = 0;

        inputIds[index] = _startToken;
        mask[index] = 1;
        index++;

        foreach (var token in tokens)
        {
            if (index >= maxLength - 1) break;
            inputIds[index] = token;
            mask[index] = 1;
            index++;
        }

        if (index < maxLength)
        {
            inputIds[index] = _endToken;
            mask[index] = 1;
        }

        return (inputIds, mask);
    }

    private List<int> Tokenize(string text)
    {
        var result = new List<int>();
        foreach (Match match in TokenRegex.Matches(text))
        {
            var token = match.Value;
            var encoded = ByteEncode(token);
            var bpeTokens = Bpe(encoded).Split(' ', StringSplitOptions.RemoveEmptyEntries);
            foreach (var part in bpeTokens)
            {
                if (_encoder.TryGetValue(part, out var id))
                {
                    result.Add(id);
                }
            }
        }

        return result;
    }

    private string Bpe(string token)
    {
        if (_cache.TryGetValue(token, out var cached)) return cached;

        var word = token.Select(ch => ch.ToString()).ToList();
        word[^1] += EndOfWord;

        var pairs = GetPairs(word);
        while (pairs.Count > 0)
        {
            var bestPair = pairs
                .Where(p => _bpeRanks.ContainsKey(p))
                .OrderBy(p => _bpeRanks[p])
                .FirstOrDefault();

            if (bestPair == default) break;

            var merged = new List<string>();
            var i = 0;
            while (i < word.Count)
            {
                var j = word.IndexOf(bestPair.Item1, i);
                if (j == -1 || j == word.Count - 1)
                {
                    merged.AddRange(word.Skip(i));
                    break;
                }

                merged.AddRange(word.Skip(i).Take(j - i));
                if (word[j + 1] == bestPair.Item2)
                {
                    merged.Add(bestPair.Item1 + bestPair.Item2);
                    i = j + 2;
                }
                else
                {
                    merged.Add(word[j]);
                    i = j + 1;
                }
            }

            word = merged;
            if (word.Count == 1) break;
            pairs = GetPairs(word);
        }

        var result = string.Join(" ", word);
        _cache[token] = result;
        return result;
    }

    private static HashSet<(string, string)> GetPairs(IReadOnlyList<string> word)
    {
        var pairs = new HashSet<(string, string)>();
        if (word.Count < 2) return pairs;

        var prev = word[0];
        for (var i = 1; i < word.Count; i++)
        {
            var current = word[i];
            pairs.Add((prev, current));
            prev = current;
        }

        return pairs;
    }

    private static string ByteEncode(string text)
    {
        var bytes = System.Text.Encoding.UTF8.GetBytes(text);
        var chars = new string[bytes.Length];
        for (var i = 0; i < bytes.Length; i++)
        {
            chars[i] = ByteEncoder[bytes[i]];
        }

        return string.Concat(chars);
    }

    private static Dictionary<string, int> LoadVocab(string path)
    {
        using var stream = File.OpenRead(path);
        var map = JsonSerializer.Deserialize<Dictionary<string, int>>(stream);
        return map ?? new Dictionary<string, int>(StringComparer.Ordinal);
    }

    private static Dictionary<(string, string), int> LoadBpeRanks(string path)
    {
        var ranks = new Dictionary<(string, string), int>();
        var lines = File.ReadAllLines(path);
        var index = 0;
        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line) || line.StartsWith("#", StringComparison.Ordinal))
            {
                continue;
            }

            var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 2) continue;
            ranks[(parts[0], parts[1])] = index++;
        }

        return ranks;
    }

    private static Dictionary<byte, string> BuildByteEncoder()
    {
        var bs = new List<int>();
        for (var i = (int)'!'; i <= (int)'~'; i++) bs.Add(i);
        for (var i = 161; i <= 172; i++) bs.Add(i);
        for (var i = 174; i <= 255; i++) bs.Add(i);

        var cs = new List<int>(bs);
        var n = 0;
        for (var b = 0; b < 256; b++)
        {
            if (bs.Contains(b)) continue;
            bs.Add(b);
            cs.Add(256 + n);
            n++;
        }

        var map = new Dictionary<byte, string>();
        for (var i = 0; i < bs.Count; i++)
        {
            map[(byte)bs[i]] = char.ConvertFromUtf32(cs[i]);
        }

        return map;
    }
}
