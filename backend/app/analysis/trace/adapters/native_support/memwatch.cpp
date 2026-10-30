// Peak heap allocation counter for the C++ measurement build.
//
// The adapter links this file into the instrumented build only; the graded
// build is untouched. It replaces the global allocation functions and keeps a
// running total of live bytes, so the trace can report "peak bytes allocated
// and not yet freed" without sampling or reading process memory.
//
// Every block carries a header holding its size. That header is a constant
// overhead per allocation and is not reported, so the number matches what the
// program asked for. The result is written as JSON to the path in CX_MEM_OUT
// when the process exits normally.

#include <cstdio>
#include <cstdlib>
#include <cstddef>
#include <new>

namespace {

std::size_t g_live = 0;
std::size_t g_peak = 0;

void on_alloc(std::size_t bytes) {
    g_live += bytes;
    if (g_live > g_peak) {
        g_peak = g_live;
    }
}

void on_free(std::size_t bytes) {
    g_live = g_live > bytes ? g_live - bytes : 0;
}

// Written at static destruction time, after main has returned. A program that
// is killed or calls _exit never reaches here; the adapter then reports no peak
// rather than a wrong one.
struct Reporter {
    ~Reporter() {
        const char *path = std::getenv("CX_MEM_OUT");
        if (path == nullptr || path[0] == '\0') {
            return;
        }
        std::FILE *file = std::fopen(path, "w");
        if (file == nullptr) {
            return;
        }
        std::fprintf(file, "{\"peak_new\": %zu}\n", g_peak);
        std::fclose(file);
    }
};

Reporter g_reporter;

}  // namespace

void *operator new(std::size_t size) {
    void *raw = std::malloc(size + sizeof(std::size_t));
    if (raw == nullptr) {
        throw std::bad_alloc();
    }
    *static_cast<std::size_t *>(raw) = size;
    on_alloc(size);
    return static_cast<char *>(raw) + sizeof(std::size_t);
}

void *operator new[](std::size_t size) {
    return operator new(size);
}

void operator delete(void *pointer) noexcept {
    if (pointer == nullptr) {
        return;
    }
    char *raw = static_cast<char *>(pointer) - sizeof(std::size_t);
    on_free(*reinterpret_cast<std::size_t *>(raw));
    std::free(raw);
}

void operator delete[](void *pointer) noexcept {
    operator delete(pointer);
}

// Sized deallocation: the compiler prefers these when the size is known, so
// they must forward to the same bookkeeping.
void operator delete(void *pointer, std::size_t) noexcept {
    operator delete(pointer);
}

void operator delete[](void *pointer, std::size_t) noexcept {
    operator delete(pointer);
}
