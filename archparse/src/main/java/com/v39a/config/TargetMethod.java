package com.v39a.config;

import java.util.Arrays;
import java.util.List;

public record TargetMethod(String methodId, String relativeFile, String methodName, List<String> paramTypes) {
    public TargetMethod(String methodId, String relativeFile, String methodName, String... paramTypes) {
        this(methodId, relativeFile, methodName, Arrays.asList(paramTypes));
    }

    public boolean matches(String simpleMethodName, int paramCount) {
        if (!this.methodName.equals(simpleMethodName)) {
            return false;
        }
        return this.paramTypes.size() == paramCount;
    }
}
