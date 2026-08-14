#pragma once

// The pinned Fluxon transfer.cu includes FlashInfer's helper header but does
// not use any declaration or macro from it.  Keeping this compatibility shim
// empty lets the focused extension compile only the seven Fluxon additions
// instead of rebuilding the complete SGLang common_ops library.
