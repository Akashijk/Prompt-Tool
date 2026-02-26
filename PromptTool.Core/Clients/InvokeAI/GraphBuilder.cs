using System;
using System.Collections.Generic;
using System.Linq;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;

namespace PromptTool.Core.Clients.InvokeAI;

public static class GraphBuilder
{
    public static string NormalizeScheduler(string scheduler)
    {
        if (string.IsNullOrWhiteSpace(scheduler)) return "dpmpp_2m_k";
        // InvokeAI prefers *_k over *_karras in the queue API.
        if (scheduler.EndsWith("_karras", StringComparison.OrdinalIgnoreCase))
        {
            return scheduler[..^"_karras".Length] + "_k";
        }
        return scheduler;
    }

    public static (InvokeAIGraph Graph, InvokeAIModel? Vae) BuildSdxlGraph(
        InvokeAIGenerationParams genParams,
        IReadOnlyList<InvokeAIModel> availableVaes)
    {
        // SDXL-specific negative prompt splitting
        var (contentNegativePrompt, styleNegativePrompt) = SplitSdxlNegativePrompt(
            genParams.NegativePrompt ?? "",
            genParams.NegativeStylePrompt);
        var positiveStylePrompt = genParams.PositiveStylePrompt;

        var (compatibleVae, vaeSourceNodeId) = GetVaeOverride(genParams, availableVaes);
        var finalCfgRescale = genParams.CfgRescaleMultiplier;
        var isDiffusers = string.Equals(genParams.Model?.Format, "diffusers", StringComparison.OrdinalIgnoreCase) || string.IsNullOrWhiteSpace(genParams.Model?.Format);
        if ((finalCfgRescale <= 0.0) && isDiffusers && (genParams.UseAutoCfgRescale ?? true))
        {
            // Diffusers SDXL models frequently need a small cfg rescale to avoid color shifts.
            finalCfgRescale = 0.7;
        }

        var vaePrecision = string.IsNullOrWhiteSpace(genParams.VaePrecision) ? "fp32" : genParams.VaePrecision!.Trim();
        var nodes = new Dictionary<string, IInvokeAINode>
        {
            ["sdxl_model_loader"] = new SdxlModelLoaderNode { Model = genParams.Model!, VaePrecision = vaePrecision },
            ["positive_prompt"] = new StringNode { Id = "positive_prompt", Value = genParams.Prompt },
            ["content_negative_prompt"] = new StringNode { Id = "content_negative_prompt", Value = contentNegativePrompt },
            ["positive_conditioning"] = new SdxlCompelPromptNode { Id = "positive_conditioning" },
            ["negative_conditioning"] = new SdxlCompelPromptNode { Id = "negative_conditioning" },
            ["noise"] = new NoiseNode { Seed = genParams.Seed, Width = genParams.Width, Height = genParams.Height, UseCpu = genParams.UseCpuNoise ?? false },
            ["sdxl_denoise_latents"] = new DenoiseLatentsNode
            {
                Id = "sdxl_denoise_latents",
                Steps = genParams.Steps,
                CfgScale = genParams.CfgScale,
                Scheduler = NormalizeScheduler(genParams.Scheduler),
                DenoisingStart = 0.0,
                DenoisingEnd = 1.0,
                CfgRescaleMultiplier = finalCfgRescale
            },
            ["l2i"] = new LatentsToImageNode { SaveToGallery = genParams.SaveToGallery, ImageCategory = "general", Fp32 = genParams.L2iFp32 ?? true }
        };

        if (!string.IsNullOrWhiteSpace(positiveStylePrompt))
        {
            nodes["positive_style_prompt"] = new StringNode { Id = "positive_style_prompt", Value = positiveStylePrompt };
        }

        if (!string.IsNullOrWhiteSpace(styleNegativePrompt))
        {
            nodes["style_negative_prompt"] = new StringNode { Id = "style_negative_prompt", Value = styleNegativePrompt };
        }

        if (compatibleVae != null)
        {
            nodes[vaeSourceNodeId] = new VaeLoaderNode { Id = vaeSourceNodeId, VaeModel = compatibleVae };
        }
        
        var (loraNodes, loraEdges, lastUnet, lastClip, lastClip2) = ChainSdxlLoras(genParams.Loras);
        foreach (var node in loraNodes)
        {
            nodes[node.Id] = node;
        }

        var edges = new List<InvokeAIEdge>
        {
            // Prompts -> Conditioning
            new() { Source = new EdgePoint { NodeId = "positive_prompt", Field = "value" }, Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "prompt" } },
            new() { Source = new EdgePoint { NodeId = "content_negative_prompt", Field = "value" }, Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "prompt" } },

            // Model/LoRA Chain -> Conditioning
            new() { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "clip" } },
            new() { Source = new EdgePoint { NodeId = lastClip2, Field = "clip2" }, Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "clip2" } },
            new() { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "clip" } },
            new() { Source = new EdgePoint { NodeId = lastClip2, Field = "clip2" }, Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "clip2" } },

            // Model/LoRA Chain -> Denoise
            new() { Source = new EdgePoint { NodeId = lastUnet, Field = "unet" }, Destination = new EdgePoint { NodeId = "sdxl_denoise_latents", Field = "unet" } },

            // Conditioning -> Denoise
            new() { Source = new EdgePoint { NodeId = "positive_conditioning", Field = "conditioning" }, Destination = new EdgePoint { NodeId = "sdxl_denoise_latents", Field = "positive_conditioning" } },
            new() { Source = new EdgePoint { NodeId = "negative_conditioning", Field = "conditioning" }, Destination = new EdgePoint { NodeId = "sdxl_denoise_latents", Field = "negative_conditioning" } },
            
            // VAE & Noise
            new() { Source = new EdgePoint { NodeId = vaeSourceNodeId, Field = "vae" }, Destination = new EdgePoint { NodeId = "l2i", Field = "vae" } },
            new() { Source = new EdgePoint { NodeId = "sdxl_denoise_latents", Field = "latents" }, Destination = new EdgePoint { NodeId = "l2i", Field = "latents" } },
            new() { Source = new EdgePoint { NodeId = "noise", Field = "noise" }, Destination = new EdgePoint { NodeId = "sdxl_denoise_latents", Field = "latents" } },
        };

        // Positive style: if provided, route through its own node; otherwise reuse the main prompt as style.
        if (!string.IsNullOrWhiteSpace(positiveStylePrompt))
        {
            edges.Add(new InvokeAIEdge
            {
                Source = new EdgePoint { NodeId = "positive_style_prompt", Field = "value" },
                Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "style" }
            });
        }
        else if (genParams.UsePromptAsStyleWhenEmpty)
        {
            edges.Add(new InvokeAIEdge
            {
                Source = new EdgePoint { NodeId = "positive_prompt", Field = "value" },
                Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "style" }
            });
        }

        if (!string.IsNullOrWhiteSpace(styleNegativePrompt))
        {
            edges.Add(new InvokeAIEdge
            {
                Source = new EdgePoint { NodeId = "style_negative_prompt", Field = "value" },
                Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "style" }
            });
        }
        
        edges.AddRange(loraEdges);

        return (new InvokeAIGraph { Nodes = nodes, Edges = edges }, compatibleVae);
    }
    
    public static (InvokeAIGraph Graph, InvokeAIModel? Vae) BuildSd15Graph(
        InvokeAIGenerationParams genParams,
        IReadOnlyList<InvokeAIModel> availableVaes)
    {
        var (compatibleVae, vaeSourceNodeId) = GetVaeOverride(genParams, availableVaes);
        var finalCfgRescale = genParams.CfgRescaleMultiplier;
        if ((finalCfgRescale <= 0.0) &&
            string.Equals(genParams.Model?.Format, "diffusers", StringComparison.OrdinalIgnoreCase) &&
            (genParams.UseAutoCfgRescale ?? true))
        {
            finalCfgRescale = 0.7;
        }
        
        var nodes = new Dictionary<string, IInvokeAINode>
        {
            ["main_model_loader"] = new MainModelLoaderNode { Model = genParams.Model! },
            ["positive_prompt"] = new StringNode { Id = "positive_prompt", Value = genParams.Prompt },
            ["negative_prompt"] = new StringNode { Id = "negative_prompt", Value = genParams.NegativePrompt ?? "" },
            ["positive_conditioning"] = new CompelNode { Id = "positive_conditioning" },
            ["negative_conditioning"] = new CompelNode { Id = "negative_conditioning" },
            ["noise"] = new NoiseNode { Seed = genParams.Seed, Width = genParams.Width, Height = genParams.Height, UseCpu = genParams.UseCpuNoise ?? false },
            ["denoise_latents"] = new DenoiseLatentsNode
            {
                Id = "denoise_latents",
                Steps = genParams.Steps,
                CfgScale = genParams.CfgScale,
                Scheduler = NormalizeScheduler(genParams.Scheduler),
                DenoisingStart = 0.0,
                DenoisingEnd = 1.0,
                CfgRescaleMultiplier = finalCfgRescale
            },
            ["l2i"] = new LatentsToImageNode { SaveToGallery = genParams.SaveToGallery, ImageCategory = "general", Fp32 = genParams.L2iFp32 ?? true }
        };

        if (compatibleVae != null)
        {
            nodes[vaeSourceNodeId] = new VaeLoaderNode { Id = vaeSourceNodeId, VaeModel = compatibleVae };
        }
        
        var (loraNodes, loraEdges, lastUnet, lastClip) = ChainSd15Loras(genParams.Loras);
        foreach (var node in loraNodes)
        {
            nodes[node.Id] = node;
        }

        var edges = new List<InvokeAIEdge>
        {
            new() { Source = new EdgePoint { NodeId = "positive_prompt", Field = "value" }, Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "prompt" } },
            new() { Source = new EdgePoint { NodeId = "negative_prompt", Field = "value" }, Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "prompt" } },
            new() { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = "positive_conditioning", Field = "clip" } },
            new() { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = "negative_conditioning", Field = "clip" } },
            new() { Source = new EdgePoint { NodeId = lastUnet, Field = "unet" }, Destination = new EdgePoint { NodeId = "denoise_latents", Field = "unet" } },
            new() { Source = new EdgePoint { NodeId = "positive_conditioning", Field = "conditioning" }, Destination = new EdgePoint { NodeId = "denoise_latents", Field = "positive_conditioning" } },
            new() { Source = new EdgePoint { NodeId = "negative_conditioning", Field = "conditioning" }, Destination = new EdgePoint { NodeId = "denoise_latents", Field = "negative_conditioning" } },
            new() { Source = new EdgePoint { NodeId = vaeSourceNodeId, Field = "vae" }, Destination = new EdgePoint { NodeId = "l2i", Field = "vae" } },
            new() { Source = new EdgePoint { NodeId = "denoise_latents", Field = "latents" }, Destination = new EdgePoint { NodeId = "l2i", Field = "latents" } },
            new() { Source = new EdgePoint { NodeId = "noise", Field = "noise" }, Destination = new EdgePoint { NodeId = "denoise_latents", Field = "latents" } }
        };
        
        edges.AddRange(loraEdges);

        return (new InvokeAIGraph { Nodes = nodes, Edges = edges }, compatibleVae);
    }
    
    private static (string content, string style) SplitSdxlNegativePrompt(string negativePrompt, string? negativeStylePrompt)
    {
        // Prefer the explicit style prompt when provided; otherwise keep the full negative prompt as content.
        var content = (negativePrompt ?? string.Empty).Trim();
        var style = (negativeStylePrompt ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(style))
        {
            return (content, string.Empty);
        }

        if (string.Equals(content, style, StringComparison.Ordinal))
        {
            return (string.Empty, style);
        }

        if (content.EndsWith(style, StringComparison.Ordinal))
        {
            content = content.Substring(0, content.Length - style.Length).TrimEnd();
        }
        else
        {
            var marker = "\n" + style;
            var index = content.LastIndexOf(marker, StringComparison.Ordinal);
            if (index >= 0 && index + marker.Length == content.Length)
            {
                content = content.Substring(0, index).TrimEnd();
            }
        }

        return (content, style);
    }
    
    private static (List<IInvokeAINode> nodes, List<InvokeAIEdge> edges, string lastUnet, string lastClip, string lastClip2) ChainSdxlLoras(List<LoraParameter> loras)
    {
        var nodes = new List<IInvokeAINode>();
        var edges = new List<InvokeAIEdge>();
        string lastUnet = "sdxl_model_loader";
        string lastClip = "sdxl_model_loader";
        string lastClip2 = "sdxl_model_loader";

        for (int i = 0; i < loras.Count; i++)
        {
            var loraInfo = loras[i];
            var loraNodeId = $"lora_loader_{i}";
            var loraNode = new SdxlLoraLoaderNode
            {
                Id = loraNodeId,
                Lora = loraInfo.Lora,
                Weight = loraInfo.Weight
            };
            nodes.Add(loraNode);

            // Determine submodel types based on LoRA info, with a fallback
            HashSet<string> submodelTypes;
            if (loraInfo.Lora.Submodels == null || !loraInfo.Lora.Submodels.Any())
            {
                // Fallback for LoRAs that don't report their submodels, to avoid the 'clip2' error.
                // Python's fallback assumes 'unet' and 'text_encoder' for robustness.
                submodelTypes = new HashSet<string> { "unet", "text_encoder" };
            }
            else
            {
                submodelTypes = new HashSet<string>(loraInfo.Lora.Submodels.Select(s => s.Type));
            }

            if (submodelTypes.Contains("unet"))
            {
                edges.Add(new InvokeAIEdge { Source = new EdgePoint { NodeId = lastUnet, Field = "unet" }, Destination = new EdgePoint { NodeId = loraNodeId, Field = "unet" } });
                lastUnet = loraNodeId;
            }
            if (submodelTypes.Contains("text_encoder"))
            {
                edges.Add(new InvokeAIEdge { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = loraNodeId, Field = "clip" } });
                lastClip = loraNodeId;
            }
            // Only add clip2 edge if explicitly in submodelTypes
            if (submodelTypes.Contains("text_encoder_2"))
            {
                edges.Add(new InvokeAIEdge { Source = new EdgePoint { NodeId = lastClip2, Field = "clip2" }, Destination = new EdgePoint { NodeId = loraNodeId, Field = "clip2" } });
                lastClip2 = loraNodeId;
            }
        }
        return (nodes, edges, lastUnet, lastClip, lastClip2);
    }
    
    private static (List<IInvokeAINode> nodes, List<InvokeAIEdge> edges, string lastUnet, string lastClip) ChainSd15Loras(List<LoraParameter> loras)
    {
        var nodes = new List<IInvokeAINode>();
        var edges = new List<InvokeAIEdge>();
        string lastUnet = "main_model_loader";
        string lastClip = "main_model_loader";

        for (int i = 0; i < loras.Count; i++)
        {
            var loraInfo = loras[i];
            var loraNodeId = $"lora_loader_{i}";
            var loraNode = new LoraLoaderNode
            {
                Id = loraNodeId,
                Lora = loraInfo.Lora,
                Weight = loraInfo.Weight
            };
            nodes.Add(loraNode);

            // Determine submodel types based on LoRA info, with a fallback
            HashSet<string> submodelTypes;
            if (loraInfo.Lora.Submodels == null || !loraInfo.Lora.Submodels.Any())
            {
                // Fallback for LoRAs that don't report their submodels.
                submodelTypes = new HashSet<string> { "unet", "text_encoder" };
            }
            else
            {
                submodelTypes = new HashSet<string>(loraInfo.Lora.Submodels.Select(s => s.Type));
            }

            if (submodelTypes.Contains("unet"))
            {
                edges.Add(new InvokeAIEdge { Source = new EdgePoint { NodeId = lastUnet, Field = "unet" }, Destination = new EdgePoint { NodeId = loraNodeId, Field = "unet" } });
                lastUnet = loraNodeId;
            }
            if (submodelTypes.Contains("text_encoder"))
            {
                edges.Add(new InvokeAIEdge { Source = new EdgePoint { NodeId = lastClip, Field = "clip" }, Destination = new EdgePoint { NodeId = loraNodeId, Field = "clip" } });
                lastClip = loraNodeId;
            }
        }
        return (nodes, edges, lastUnet, lastClip);
    }
    
    private static (InvokeAIModel? vae, string sourceNodeId) GetVaeOverride(InvokeAIGenerationParams genParams, IReadOnlyList<InvokeAIModel> availableVaes)
    {
        var mainModel = genParams.Model;
        if (!string.IsNullOrWhiteSpace(genParams.VaeUsedName))
        {
            var desired = genParams.VaeUsedName.Trim();
            var match = availableVaes.FirstOrDefault(v =>
                string.Equals(v.Name, desired, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(v.Key, desired, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(v.Hash, desired, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                var nodeId = mainModel?.Base == "sdxl" ? "sdxl_fp32_vae_loader" : "sd15_fp32_vae_loader";
                return (match, nodeId);
            }
        }

        if (mainModel?.Base == "sdxl")
        {
            // Prefer an fp32-friendly SDXL VAE, mirroring the Qt app's stability behavior.
            var sdxlVaes = availableVaes.Where(v => string.Equals(v.Base, "sdxl", StringComparison.OrdinalIgnoreCase)).ToList();
            var fp16Fix = sdxlVaes.FirstOrDefault(v => v.Name.Contains("sdxl-vae-fp16-fix", StringComparison.OrdinalIgnoreCase));
            if (fp16Fix != null) return (fp16Fix, "sdxl_fp32_vae_loader");

            var nonFp16 = sdxlVaes.FirstOrDefault(v => !v.Name.Contains("fp16", StringComparison.OrdinalIgnoreCase));
            if (nonFp16 != null) return (nonFp16, "sdxl_fp32_vae_loader");

            // Fallback to the model's bundled VAE.
            return (null, "sdxl_model_loader");
        }
        else if (mainModel?.Base is "sd-1.5" or "sd-1")
        {
            var sd15Vaes = availableVaes.Where(v => v.Base == "sd-1" || string.IsNullOrEmpty(v.Base)).ToList();
            var mse = sd15Vaes.FirstOrDefault(v => v.Name.Contains("sd-vae-ft-mse", StringComparison.OrdinalIgnoreCase));
            if (mse != null) return (mse, "sd15_fp32_vae_loader");
            if (sd15Vaes.Any()) return (sd15Vaes.First(), "sd15_fp32_vae_loader");
        }

        return (null, mainModel?.Base == "sdxl" ? "sdxl_model_loader" : "main_model_loader");
    }
}
