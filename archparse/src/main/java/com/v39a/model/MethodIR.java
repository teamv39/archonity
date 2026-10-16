package com.v39a.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.ArrayList;
import java.util.List;

public class MethodIR {
    @JsonProperty("method_id")
    private String methodId;

    @JsonProperty("file")
    private String file;

    @JsonProperty("branches")
    private List<BranchIR> branches = new ArrayList<>();

    @JsonProperty("calls")
    private List<CallIR> calls = new ArrayList<>();

    @JsonProperty("unsupported")
    private List<String> unsupported = new ArrayList<>();

    public MethodIR() {}

    public MethodIR(String methodId, String file) {
        this.methodId = methodId;
        this.file = file;
    }

    public String getMethodId() {
        return methodId;
    }

    public void setMethodId(String methodId) {
        this.methodId = methodId;
    }

    public String getFile() {
        return file;
    }

    public void setFile(String file) {
        this.file = file;
    }

    public List<BranchIR> getBranches() {
        return branches;
    }

    public void setBranches(List<BranchIR> branches) {
        this.branches = branches;
    }

    public List<CallIR> getCalls() {
        return calls;
    }

    public void setCalls(List<CallIR> calls) {
        this.calls = calls;
    }

    public List<String> getUnsupported() {
        return unsupported;
    }

    public void setUnsupported(List<String> unsupported) {
        this.unsupported = unsupported;
    }
}
